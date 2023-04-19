import argparse
import boto3
from decimal import Decimal
import json
import requests
from python_graphql_client import GraphqlClient
import os
from dotenv import load_dotenv
from copy import deepcopy
import yaml
import mariadb
from datetime import datetime

load_dotenv()
TWOPLACES = Decimal(10) ** -2


class Monarch:
    token = ''
    client = ''

    def __init__(self, username, password):
        r = requests.post('https://api.monarchmoney.com/auth/login/', data={
            'username': username,
            'password': password,
            'supports_mfa': 'false',
            'trusted_device': 'true'
        })
        self.token = json.loads(r.content)['token']
        print(self.token)
        self.headers = {
            "Authorization": f"Token {self.token}"
        }
        self.client = GraphqlClient(
            endpoint='https://api.monarchmoney.com/graphql', headers=self.headers)

    def get_accounts(self):
        operation_name = 'GetAccountsPage'
        variables = {}
        query = """
query GetAccountsPage {
  hasAccounts
  accounts {
    id
    displayBalance
    displayName
    updatedAt
    isHidden
    __typename
  }
}
"""
        return self.client.execute(
            query=query, operation_name=operation_name, variables=variables
        )

    def get_all_holdings(self):
        operation_name = 'Web_GetHoldings'
        variables = {
            "input": {
                "startDate": "2022-12-29",
                "endDate": "2023-01-29"
            }
        }
        query = """
query Web_GetHoldings($input: PortfolioInput) {
  portfolio(input: $input) {
    aggregateHoldings {
      edges {
        node {
          id
          quantity
          basis
          totalValue
          lastSyncedAt
          holdings {
            account {
              id
              displayName
              __typename
            }
            id
            name
            ticker
            closingPrice
            closingPriceUpdatedAt
            quantity
            value
            __typename
          }
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
"""
        return self.client.execute(
            query=query, operation_name=operation_name, variables=variables
        )


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
        total += value if type(value) == float else sum(value.values())
    return total


def investments_to_holdings(invests, id):
    ret = []
    for line in invests:
        for holding in line['node']['holdings']:
            if holding['account']['id'] == id:
                if args.debug:
                    print(f"{id}: {holding['id']}")
                ret.append({
                    'symbol': holding['ticker'],
                    'value': holding['value'],
                    'account_id': id
                })
    return ret


def get_actual_allocation(config, accounts, invests):
    actual = deepcopy(config['allocation'])
    for key in actual:
        actual[key] = 0.0
    actual['none'] = {}
    actual['other'] = 0.0

    for account in config['accounts']:
        ALL_ACCOUNTS[account['id']] = account['memo']
        for line in accounts:
            if account['id'] == line['id']:
                if account['type'] == 'invest':
                    for holding in investments_to_holdings(invests, line['id']):
                        if holding['symbol'] in SYMBOLS:
                            if SYMBOLS[holding['symbol']] == 'none':
                                actual['none'][holding['account_id']
                                               ] = holding['value']
                            else:
                                actual[SYMBOLS[holding['symbol']]
                                       ] += holding['value']
                        else:
                            actual['other'] += holding['value']
                else:
                    actual[account['type']] += line['displayBalance']

    return actual


def needs_rebalance(actual, desired):
    threshold = CONFIG['threshold']
    total = get_actual_total(actual)

    for asset_type in desired:
        if asset_type == 'other': # TODO: Only skip if below threshold
           continue
        min_band = total*(desired[asset_type] -
                          desired[asset_type]*threshold/100)/100
        max_band = total*(desired[asset_type] +
                          desired[asset_type]*threshold/100)/100

        if actual[asset_type] < min_band or actual[asset_type] > max_band:
            return True

    return False


def needs_invest(actual):
    if len(actual['none']) > 0:
        return max(actual['none'].values()) >= MIN_INVEST
    return False


def find_sell(allocation, actual):
    total = get_actual_total(actual)
    threshold = CONFIG['threshold']

    for asset in allocation:
        if asset in ["none", "other"]:
            continue
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
    total_wo_other = total - actual.get('other', 0)
    percent_wo_other = 100 - allocation.get('other', 0)
    while buy and available > 0:
        gap = round(max(total_wo_other*allocation[buy]/percent_wo_other - actual[buy], 0))
        howmuch = min(available, gap)
        rec.append(
            {'asset': buy, 'rec': CONFIG['preferred'][buy], 'amount': howmuch})
        available -= howmuch
        used.append(buy)
        buy = find_min(actual, used)

    return rec


def total_available(none):
    return sum([v for v in none.values() if v > MIN_INVEST])

def rebalance(config, actual):
    allocation = config['allocation']
    tax = config['options']['tax']
    total = get_actual_total(actual)
    rec = {
        'buy': [],
        'sell': []
    }

    if tax:  # optimize tax (sell less)
        if sell := find_sell(allocation, actual):
            print(sell)
            available = round(actual[sell] - total *
                              allocation[sell]/100 + total_available(actual['none']))
            rec['sell'].append({'asset': sell, 'amount': available})
            used = [sell, 'none', 'other']
            rec['buy'] = buy_recommendations(
                actual, available, total, allocation, used)
    return rec


def invest(config, actual):
    allocation = config['allocation']
    total = get_actual_total(actual)
    available = total_available(actual['none'])
    used = ['none', 'other']
    return {
        'buy': buy_recommendations(actual, available, total, allocation, used),
        'sell': []
    }


def needs_sweep(accounts):
    for line in accounts:
        if line["id"] == CONFIG["main"]["account"]:
            config = CONFIG["main"]
            if line["displayBalance"] > config["high"]:
                return line["displayBalance"] - config["high"] + (config["high"] - config["low"])/2
            if line["displayBalance"] < config["low"]:
                return line["displayBalance"] - config["low"] - (config["high"] - config["low"])/2

    return 0


def vested(accounts):
    return any(
        line["id"] in CONFIG["vesting"]
        and float(line["displayBalance"]) > 0.01
        for line in accounts
    )


def pretty_rec(message, available: dict):
    out = "SELL:\n"
    for rec in message['sell']:
        out += f' {rec["asset"]}: {Decimal(rec["amount"]).quantize(TWOPLACES)}\n'
    out += "BUY:\n"
    for rec in message['buy']:
        out += f' {rec["asset"]} ({rec["rec"]}): {Decimal(rec["amount"]).quantize(TWOPLACES)}\n'
    if len(available) > 0:
        out += "AVAILABLE:\n"
        for aid, avalue in available.items():
            if avalue > MIN_INVEST:
                out += f' {ALL_ACCOUNTS[aid]}: {avalue}\n'
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
        for account in allocation if account != 'none'
    }


def updatedb(account, allocation):
    table = boto3.resource('dynamodb').Table('finance')
    total = Decimal(get_actual_total(allocation)).quantize(TWOPLACES)
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
MIN_INVEST = CONFIG['min_investment_balance']
ALL_ACCOUNTS = {}

monarch = Monarch(os.environ['MONARCH_USERNAME'],
                  os.environ['MONARCH_PASSWORD'])
# print(json.dumps(monarch.get_holdings('125631306450064687')))
invests = monarch.get_all_holdings()

accounts = monarch.get_accounts()

if args.debug:
    with open('./out/accounts.json', "w") as file:
        file.write(json.dumps(accounts, indent=4, sort_keys=True, default=str))
    with open('./out/invests.json', "w") as file:
        file.write(json.dumps(invests, indent=4, sort_keys=True, default=str))

accounts_to_eval = account_config.keys()
if args.account != "":
    accounts_to_eval = [args.account]

for account in accounts_to_eval:
    print(account)
    allocation = get_actual_allocation(
        account_config[account], accounts['data']['accounts'], invests['data']['portfolio']['aggregateHoldings']['edges'])
    print(allocation)

    rec = ""
    if needs_invest(allocation):
        rec = f"Found money in {account}\n" + \
            pretty_rec(invest(account_config[account], allocation), allocation["none"])
        print(rec)
        if not args.local:
            send_notification(f"Found money in {account}", rec)
    elif needs_rebalance(allocation, account_config[account]['allocation']):
        rec = f"{account} needs rebalance!\n" + \
            pretty_rec(rebalance(account_config[account], allocation), allocation["none"])
        print(rec)
        if not args.local:
            send_notification(f"{account} needs rebalance!", rec)
    else:
        print("OK\n")

    if not args.local:
        updatedb(account, allocation)

sweep = needs_sweep(accounts['data']['accounts'])
if sweep != 0:
    print(f"Main account needs sweep: {sweep}")
    if not args.local:
        send_notification("Main account needs sweep",
                          f"Deposit {sweep} into checking" if sweep < 0 else f"Withdraw {sweep} out of checking")

if vested(accounts["data"]["accounts"]):
    print("Balance in vesting account")
    if not args.local:
        send_notification("Vesting available",
                          "Go to MorganStanley and sell available stock")
