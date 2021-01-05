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
    actual['none'] = 0.0

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


def needs_invest(actual):
    return actual['none'] > 1.0


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


def buy_recommendations(actual, available, total, allocation, used):
    rec = []
    buy = find_min(actual, used)
    while buy and available > 0:
        gap = round(max(total*allocation[buy]/100 - actual[buy], 0))
        howmuch = min(available, gap)
        rec.append(
            {'asset': f"{buy} ({CONFIG['preferred'][buy]})", 'amount': howmuch})
        available -= howmuch
        used.append(buy)
        buy = find_min(actual, used)

    return rec


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
            available = round(actual[sell] - total*allocation[sell]/100 + actual['none'])
            rec['sell'].append({'asset': sell, 'amount': available})
            used = [sell, 'none']
            rec['buy'] = buy_recommendations(
                actual, available, total, allocation, used)
    else:  # rebalance everything
        pass

    return rec


def invest(config, actual):
    allocation = config['allocation']
    total = get_actual_total(actual)
    available = actual['none']
    used = ['none']
    rec = {
        'buy': buy_recommendations(actual, available, total, allocation, used),
        'sell': []
    }

    return rec


def pretty_rec(message):
    out = "SELL:\n"
    for rec in message['sell']:
        out += f' {rec["asset"]}: {rec["amount"]}\n'
    out += "BUY:\n"
    for rec in message['buy']:
        out += f' {rec["asset"]}: {rec["amount"]}\n'
    return out


def send_notification(subject, message):
    sns = boto3.resource('sns')
    topic = sns.Topic(os.environ['AWS_TOPIC_ARN'])
    response = topic.publish(
        Subject=subject,
        Message=message
    )
    print(response)


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
    print(account)
    allocation = get_actual_allocation(
        account_config[account], accounts, invests)
    print(allocation)

    if needs_invest(allocation):
        print("Found non-invested money")
        send_notification(f"Found money in {account}", f"Found money in {account}\n" + pretty_rec(
            invest(account_config[account], allocation)))
    elif needs_rebalance(allocation, account_config[account]['allocation']):
        print("Found rebalance")
        send_notification(f"{account} needs rebalance!", f"{account} needs rebalance!\n" +
                          pretty_rec(recommendation(account_config[account], allocation)))
    else:
        print("OK")

