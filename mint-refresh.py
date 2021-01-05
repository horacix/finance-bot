import os
import mintapi
from dotenv import load_dotenv
load_dotenv()

mint = mintapi.Mint(
    os.environ['API_USER'],
    os.environ['API_PASSWORD'],
    mfa_method='soft-token',
    mfa_token=os.environ['MFA_TOKEN'],
    headless=True,
    use_chromedriver_on_path=True
)
mint.initiate_account_refresh()
mint.close()
