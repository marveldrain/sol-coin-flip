from flask import Flask, request, jsonify, render_template
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solana.transaction import Transaction
import os
import hashlib
import secrets
import time
import json
from pathlib import Path

app = Flask(__name__)

HOUSE_KEYPAIR = Keypair.from_base58_string(os.getenv("HOUSE_PRIVATE_KEY"))
RPC = "https://api.devnet.solana.com"
client = Client(RPC)
SERVER_SEED = secrets.token_hex(32)

BALANCES_FILE = Path("balances.json")
balances = json.loads(BALANCES_FILE.read_text()) if BALANCES_FILE.exists() else {}
user_deposits = {}  # user_id -> deposit_keypair

def save_balances():
    BALANCES_FILE.write_text(json.dumps(balances))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_deposit_address', methods=['POST'])
def get_deposit():
    data = request.json
    user_id = data.get('user_id', secrets.token_hex(12))
    
    if user_id not in user_deposits:
        user_deposits[user_id] = Keypair()   # Fixed correct constructor
    
    deposit_kp = user_deposits[user_id]
    return jsonify({
        "deposit_address": str(deposit_kp.pubkey()),
        "user_id": user_id
    })

@app.route('/balance', methods=['POST'])
def user_balance():
    data = request.json
    user_id = data['user_id']
    
    # AUTO CREDIT - Check real on-chain balance
    if user_id in user_deposits:
        deposit_pubkey = user_deposits[user_id].pubkey()
        onchain_bal = client.get_balance(deposit_pubkey).value
        
        # Credit any new SOL received
        current = balances.get(user_id, 0)
        if onchain_bal > current:
            balances[user_id] = onchain_bal
            save_balances()
    
    bal = balances.get(user_id, 0) / 1e9
    return jsonify({"balance_sol": round(bal, 4)})

# Keep flip and withdraw same as before (copy from previous if needed)
@app.route('/flip', methods=['POST'])
def coin_flip():
    data = request.json
    user_id = data['user_id']
    amount_sol = float(data['amount_sol'])
    user_choice = data.get('choice')

    amount_lamports = int(amount_sol * 1_000_000_000)

    if user_id not in balances or balances[user_id] < amount_lamports:
        return jsonify({"error": "Insufficient balance"})

    balances[user_id] -= amount_lamports

    recent_blockhash = str(client.get_latest_blockhash().value.blockhash)
    combined = f"{SERVER_SEED}:{user_id}:{recent_blockhash}:{time.time()}".encode()
    vrf_hash = hashlib.sha256(combined).hexdigest()
    random_int = int(vrf_hash, 16) % 2
    flip_result = "heads" if random_int == 0 else "tails"

    won = (user_choice is None) or (flip_result == user_choice)
    if won:
        payout = int(amount_lamports * 1.98)
        balances[user_id] += payout
        payout_sol = round(payout / 1e9, 4)
    else:
        payout_sol = 0

    save_balances()
    return jsonify({"result": flip_result, "won": won, "payout_sol": payout_sol})

@app.route('/withdraw', methods=['POST'])
def withdraw():
    # same as previous version
    data = request.json
    user_id = data['user_id']
    amount_sol = float(data['amount_sol'])
    destination = data['destination']

    amount_lamports = int(amount_sol * 1_000_000_000)
    if user_id not in balances or balances[user_id] < amount_lamports:
        return jsonify({"error": "Insufficient balance"})

    balances[user_id] -= amount_lamports
    save_balances()

    try:
        tx = Transaction().add(transfer(TransferParams(
            from_pubkey=HOUSE_KEYPAIR.pubkey(),
            to_pubkey=Pubkey.from_string(destination),
            lamports=amount_lamports
        )))
        tx_sig = client.send_transaction(tx, HOUSE_KEYPAIR).value
        return jsonify({"success": True, "tx": str(tx_sig)})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
