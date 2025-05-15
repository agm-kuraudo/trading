import requests

# Initial POST request to get the tokens
url = 'https://demo-api.ig.com/gateway/deal/session'
payload = {
    "identifier": "MY_LIVE",
    "password": "AlphaTest1",
    "encryptedPassword": None
}

headers = {
    'Content-Type': 'application/json; charset=UTF-8',
    'Accept': 'application/json; charset=UTF-8',
    'X-IG-API-KEY': '47a0bdbd202adb18f33be15fe64f99518142b9c7',
    'Version': '2'
}

response = requests.post(url, json=payload, headers=headers)

if response.status_code == 200:
    print('Request was successful!')
    print(response.json())
else:
    print('An error occurred:', response.status_code)
    print(response.text)
    exit(1)

# Extract tokens from response headers
cst_token = response.headers.get('CST')
x_security_token = response.headers.get('X-SECURITY-TOKEN')
print('CST:', cst_token)
print('X-SECURITY-TOKEN:', x_security_token)

# Extract account information from response body
response_data = response.json()
current_account_id = response_data['currentAccountId']
accounts = response_data['accounts']
balances = response_data['accountInfo']

print(accounts)
print(balances)

print('Current Account ID:', current_account_id)
print('Account One:', accounts[0]["accountId"])
print('Account Two:', accounts[1]["accountId"])
print('Balance:', balances["balance"])


# Example of a future request using the tokens
# future_url = 'https://demo-api.ig.com/gateway/deal/some_endpoint'
future_headers = {
    'Content-Type': 'application/json; charset=UTF-8',
    'Accept': 'application/json; charset=UTF-8',
    'X-IG-API-KEY': '47a0bdbd202adb18f33be15fe64f99518142b9c7',
    'Version': '2',
    'CST': cst_token,
    'X-SECURITY-TOKEN': x_security_token
}


#Search for GBP/USD and get the EPIC

# future_response = requests.get(future_url, headers=future_headers)
#
# if future_response.status_code == 200:
#     print('Future request was successful!')
#     print(future_response.json())  # Assuming the response is in JSON format
# else:
#     print('An error occurred:', future_response.status_code)
#     print(future_response.text)
