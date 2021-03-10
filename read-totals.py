import boto3
from pprint import pprint
from dotenv import load_dotenv

load_dotenv()

table = boto3.resource('dynamodb').Table('finance')
response = table.scan()
pprint(response.get('Items', []))
