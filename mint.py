import json
import mintapi
import os
from dotenv import load_dotenv
from copy import deepcopy
import yaml

load_dotenv()


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


with open(r'./accounts.yml') as file:
    account_config = yaml.load(file, Loader=yaml.FullLoader)
with open(r'./symbols.yml') as file:
    SYMBOLS = yaml.load(file, Loader=yaml.FullLoader)

mint = mintapi.Mint(
    os.environ['API_USER'],
    os.environ['API_PASSWORD'],
    mfa_method='sms',
    headless=True
)

invests = json.loads(mint.get_invests_json())
accounts = mint.get_accounts()

# for account in account_config:
allocation = get_actual_allocation(
    account_config['default'], accounts, invests)
print(allocation)
