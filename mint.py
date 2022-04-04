import argparse
import boto3
from decimal import Decimal
import json
import mintapi
import os
from dotenv import load_dotenv
from copy import deepcopy
import yaml
import mariadb
from datetime import datetime

load_dotenv()
TWOPLACES = Decimal(10) ** -2


def read_args():
    parser = argparse.ArgumentParser(
        description="Get Mint data and update recommendations"
    )
    parser.add_argument("--local", action="store_true",
                        help="Print recommendations locally. (Don't use SNS)")
    parser.add_argument("--debug", action="store_true",
                        help="Print downloaded json data")
    parser.add_argument("--account", nargs="?", default="",
                        help="Specific account")
    return parser.parse_args()


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
        if found and value > actual[asset] or not found:
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
        if sell := find_sell(allocation, actual):
            available = round(actual[sell] - total *
                              allocation[sell]/100 + actual['none'])
            rec['sell'].append({'asset': sell, 'amount': available})
            used = [sell, 'none']
            rec['buy'] = buy_recommendations(
                actual, available, total, allocation, used)
    return rec


def invest(config, actual):
    allocation = config['allocation']
    total = get_actual_total(actual)
    available = actual['none']
    used = ['none']
    return {
        'buy': buy_recommendations(actual, available, total, allocation, used),
        'sell': []
    }


def needs_sweep(accounts):
    for line in accounts:
        if line["id"] == CONFIG["main"]["account"]:
            config = CONFIG["main"]
            if line["value"] > config["high"]:
                return line["value"] - config["high"] + (config["high"] - config["low"])/2
            if line["value"] < config["low"]:
                return line["value"] - config["low"] - (config["high"] - config["low"])/2

    return 0


def pretty_rec(message):
    out = "SELL:\n"
    for rec in message['sell']:
        out += f' {rec["asset"]}: {Decimal(rec["amount"]).quantize(TWOPLACES)}\n'
    out += "BUY:\n"
    for rec in message['buy']:
        out += f' {rec["asset"]}: {Decimal(rec["amount"]).quantize(TWOPLACES)}\n'
    return out


def send_notification(subject, message):
    sns = boto3.resource('sns')
    topic = sns.Topic(os.environ['AWS_TOPIC_ARN'])
    response = topic.publish(
        Subject=subject,
        Message=message
    )
    print(response)


def decimal_allocation(allocation):
    return {
        account: Decimal(allocation[account]).quantize(TWOPLACES)
        for account in allocation
    }


def updatedb(account, allocation):
    table = boto3.resource('dynamodb').Table('finance')
    total = Decimal(sum(allocation.values())).quantize(TWOPLACES)
    print(total)

    response = table.update_item(
        Key={
            'account': account
        },
        UpdateExpression='SET allocation=:a, balance=:t',
        ExpressionAttributeValues={
            ':a': decimal_allocation(allocation),
            ':t': total
        }
    )
    if args.debug:
        print(response)

    try:
        conn = mariadb.connect(
            user=os.environ['DATABASE_USER'],
            password=os.environ['DATABASE_PASSWORD'],
            host=os.environ['DATABASE_HOST'],
            port=3306,
            database=os.environ['DATABASE'],
            autocommit=True
        )
    except mariadb.Error as e:
        print(f"Error connecting to MariaDB Platform: {e}")
        return

    cur = conn.cursor()
    cur.execute(
        "SELECT account_id FROM accounts WHERE account_name=?", (account,))

    account_id = -1
    for row in cur:
        account_id = row[0]

    cur.execute(
        "INSERT INTO balances (account_id, balance_date, balance_amount) VALUES (?, ?, ?) ON DUPLICATE KEY UPDATE balance_amount=?",
        (account_id, datetime.now().isoformat(), total, total)
    )

    conn.close()


# Read configuration
args = read_args()
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

accounts = mint.get_accounts()
invests = json.loads(mint.get_invests_json())
mint.initiate_account_refresh()
mint.close()

with open('./accounts.json', "w") as file:
    file.write(json.dumps(accounts, indent=4, sort_keys=True, default=str))
with open('./invests.json', "w") as file:
    file.write(json.dumps(invests, indent=4, sort_keys=True, default=str))

accounts_to_eval = account_config.keys()
if args.account != "":
    accounts_to_eval = [args.account]

for account in accounts_to_eval:
    print(account)
    allocation = get_actual_allocation(
        account_config[account], accounts, invests)
    print(allocation)

    rec = ""
    if needs_invest(allocation):
        rec = f"Found money in {account}\n" + \
            pretty_rec(invest(account_config[account], allocation))
        print(rec)
        if not args.local:
            send_notification(f"Found money in {account}", rec)
    elif needs_rebalance(allocation, account_config[account]['allocation']):
        rec = f"{account} needs rebalance!\n" + \
            pretty_rec(recommendation(account_config[account], allocation))
        print(rec)
        if not args.local:
            send_notification(f"{account} needs rebalance!", rec)
    else:
        print("OK\n")

    updatedb(account, allocation)

sweep = needs_sweep(accounts)
if sweep != 0:
    print(f"Main account needs sweep: {sweep}")
    if not args.local:
        send_notification("Main account needs sweep",
                          f"Deposit {sweep} into checking" if sweep < 0 else f"Withdraw {sweep} out of checking")
