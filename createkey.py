from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12 
import datetime

app = Flask(__name__)

@app.route('/create_key', methods=['POST'])
def create_key():
    try:
        # Lấy dữ liệu từ JSON request
        data = request.get_json()
        user_id = data.get('user_id')
        user_name = data.get('user_name')

        if not user_id or not user_name:
            return jsonify({"error": "user_id và user_name là bắt buộc"}), 400

        # 1. Tạo Private Key
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        # 2. Tạo Certificate tự ký
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"Nguyen Quang Tung"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10))
            .sign(key, hashes.SHA256())
        )

        # 3. Lưu thành file .pfx (PKCS#12)
        with open("my_cert.pfx", "wb") as f:
            # SỬA DÒNG NÀY: Dùng trực tiếp pkcs12.serialize... thay vì serialization.pkcs12...
            f.write(pkcs12.serialize_key_and_certificates(
                b"my_cert", key, cert, None, serialization.BestAvailableEncryption(b"1234")
            ))

        return jsonify({"message": "Tạo key thành công", "key": "my_cert.pfx"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)