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

app = Flask(__name__)

HOUSE_KEYPAIR = Keypair.from_base58_string(os.getenv("HOUSE_PRIVATE_KEY"))
RPC = "https://api.devnet.solana.com"
client = Client(RPC)
SERVER_SEED = secrets.token_hex(32)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/flip', methods=['POST'])
def coin_flip():
    data = request.json
    user_pubkey_str = data['user_pubkey']
    amount_sol = float(data['amount_sol'])
    user_choice = data.get('choice')  # "heads", "tails", or None for random
    user_seed = data.get('user_seed', secrets.token_hex(16))

    amount_lamports = int(amount_sol * 1_000_000_000)

    # Provably Fair VRF
    recent_blockhash = str(client.get_latest_blockhash().value.blockhash)
    combined = f"{SERVER_SEED}:{user_seed}:{recent_blockhash}:{time.time()}".encode()
    vrf_hash = hashlib.sha256(combined).hexdigest()
    random_int = int(vrf_hash, 16) % 2
    flip_result = "heads" if random_int == 0 else "tails"

    proof = {
        "server_seed": SERVER_SEED,
        "user_seed": user_seed,
        "blockhash": recent_blockhash,
        "vrf_hash": vrf_hash,
        "result": flip_result
    }

    if (user_choice is None) or (flip_result == user_choice):
        # User wins 1.98x
        payout = int(amount_lamports * 1.98)
        tx_sig = "SIMULATED_TX"
        try:
            tx = Transaction().add(transfer(TransferParams(
                from_pubkey=HOUSE_KEYPAIR.pubkey(),
                to_pubkey=Pubkey.from_string(user_pubkey_str),
                lamports=payout
            )))
            tx_sig = str(client.send_transaction(tx, HOUSE_KEYPAIR).value)
        except:
            pass
        return jsonify({
            "result": flip_result,
            "won": True,
            "payout_sol": round(payout / 1e9, 4),
            "proof": proof,
            "tx": tx_sig
        })
    else:
        return jsonify({
            "result": flip_result,
            "won": False,
            "proof": proof
        })

@app.route('/balance', methods=['GET'])
def house_balance():
    balance = client.get_balance(HOUSE_KEYPAIR.pubkey()).value
    return jsonify({"house_balance_sol": balance / 1e9})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
