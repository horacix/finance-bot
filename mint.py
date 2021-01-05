import boto3
import json
import mintapi
import os
from dotenv import load_dotenv
from copy import deepcopy
import yaml

load_dotenv()


def load_config(filename):
    with open(filename) as file:
        contents = yaml.load(file, Loader=yaml.FullLoader)
    return contents


def get_actual_total(actual):
    total = 0.0
    for value in actual.values():
        total += value
    return total


def get_actual_allocation(config, accounts, invests):
    actual = deepcopy(config['allocation'])
    for key in actual:
        actual[key] = 0.0

    for account in config['accounts']:
        for line in accounts:
            if account['id'] == line['id']:
                if account['type'] == 'invest':
                    for holding in invests[str(account['id'])]['holdings'].values():
                        actual[SYMBOLS[holding['symbol']]] += holding['value']
                else:
                    actual[account['type']] += line['value']

    return actual


def needs_rebalance(actual, desired):
    threshold = CONFIG['threshold']
    total = get_actual_total(actual)

    for asset_type in desired:
        min_band = total*(desired[asset_type] -
                          desired[asset_type]*threshold/100)/100
        max_band = total*(desired[asset_type] +
                          desired[asset_type]*threshold/100)/100

        if actual[asset_type] < min_band or actual[asset_type] > max_band:
            return True

    return False


def find_sell(allocation, actual):
    total = get_actual_total(actual)
    threshold = CONFIG['threshold']

    for asset in allocation:
        target = total*allocation[asset]/100
        diff = (actual[asset]-target)/target
        if diff > threshold/100:
            return asset

    return None


def find_min(actual, used):
    found = None
    value = 99999999
    for asset in actual:
        if asset in used:
            continue
        if found:
            if value > actual[asset]:
                found = asset
                value = actual[asset]
        else:
            found = asset
            value = actual[asset]

    return found


def recommendation(config, actual):
    allocation = config['allocation']
    tax = config['options']['tax']
    total = get_actual_total(actual)
    rec = {
        'buy': [],
        'sell': []
    }

    if tax:  # optimize tax (sell less)
        sell = find_sell(allocation, actual)
        if sell:
            available = round(actual[sell] - total*allocation[sell]/100)
            rec['sell'].append({'asset': sell, 'amount': available})
            used = [sell]
            buy = find_min(actual, used)
            while buy and available > 0:
                gap = round(max(total*allocation[buy]/100 - actual[buy], 0))
                howmuch = min(available, gap)
                rec['buy'].append(
                    {'asset': f"{buy} ({CONFIG['preferred'][buy]})", 'amount': howmuch})
                available -= howmuch
                used.append(buy)
                buy = find_min(actual, used)
    else:  # rebalance everything
        rec = "hola"

    return (rec)


def pretty_rec(message):
    out = "SELL:\n"
    for rec in message['sell']:
        out += f' {rec["asset"]}: {rec["amount"]}\n'
    out += "BUY:\n"
    for rec in message['buy']:
        out += f' {rec["asset"]}: {rec["amount"]}\n'
    return out


account_config = load_config(r'./accounts.yml')
SYMBOLS = load_config(r'./symbols.yml')
CONFIG = load_config(r'./config.yml')

mint = mintapi.Mint(
    os.environ['API_USER'],
    os.environ['API_PASSWORD'],
    mfa_method='soft-token',
    mfa_token=os.environ['MFA_TOKEN'],
    headless=True,
    use_chromedriver_on_path=True,
    wait_for_sync=False
)

invests = json.loads(mint.get_invests_json())
accounts = mint.get_accounts()
mint.close()

for account in account_config:
    allocation = get_actual_allocation(
        account_config[account], accounts, invests)
    print(allocation)

    if needs_rebalance(allocation, account_config[account]['allocation']):
        print("Found rebalance")
        sns = boto3.resource('sns')
        topic = sns.Topic(os.environ['AWS_TOPIC_ARN'])
        response = topic.publish(
            Subject=f"{account} needs rebalance!",
            Message=f"{account} needs rebalance!\n" + pretty_rec(recommendation(
                account_config[account], allocation))
        )
        print(response)
