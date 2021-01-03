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
    total = 0.0
    for value in actual.values():
        total += value

    for asset_type in desired:
        min_band = total*(desired[asset_type] -
                          desired[asset_type]*threshold/100)/100
        max_band = total*(desired[asset_type] +
                          desired[asset_type]*threshold/100)/100

        print(
            f'Asset[{asset_type}]: {min_band} - {max_band}, actual: {actual[asset_type]}')
        if actual[asset_type] < min_band or actual[asset_type] > max_band:
            return True

    return False


account_config = load_config(r'./accounts.yml')
SYMBOLS = load_config(r'./symbols.yml')
CONFIG = load_config(r'./config.yml')

mint = mintapi.Mint(
    os.environ['API_USER'],
    os.environ['API_PASSWORD'],
    mfa_method='sms',
    headless=True
)

invests = json.loads(mint.get_invests_json())
accounts = mint.get_accounts()

for account in account_config:
    allocation = get_actual_allocation(
        account_config[account], accounts, invests)
    print(allocation)

    if needs_rebalance(allocation, account_config[account]['allocation']):
        print(f"{account} needs rebalance!")
