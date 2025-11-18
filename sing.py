from flask import Flask, request, jsonify
from pyhanko.sign import signers, fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.stamp import TextStampStyle
import os
import glob

app = Flask(__name__)

@app.route('/api/sign_pdf', methods=['POST'])
def sign_pdf():
    try:
        # Lấy dữ liệu từ JSON request
        data = request.get_json()
        meeting_id = data.get('meeting_id')
        user_id = data.get('user_id')
        user_name = data.get('user_name')

        if not all([meeting_id, user_id, user_name]):
            return jsonify({"error": "Các tham số meeting_id, user_id, user_name là bắt buộc"}), 400

        # Đường dẫn file PDF và file PFX
        pdf_files = glob.glob(os.path.join('meetings', meeting_id, 'final', '*.pdf'))
        if not pdf_files:
            return jsonify({"error": f"Không tìm thấy file PDF nào trong thư mục meetings/{meeting_id}/final"}), 404

        input_pdf = pdf_files[0]

        output_pdf = os.path.join('meetings', meeting_id, 'final', f'signed_by_{user_id}-{user_name}.pdf')

        pfx_file = os.path.join('keys', f'{user_id}-{user_name}.pfx')
        passphrase = f'actvn@edu.vn{user_id}-{user_name}'

        if not os.path.exists(input_pdf):
            return jsonify({"error": f"File {input_pdf} không tồn tại"}), 404

        if not os.path.exists(pfx_file):
            return jsonify({"error": f"File {pfx_file} không tồn tại"}), 404

        # 1. Load Signer
        signer = signers.SimpleSigner.load_pkcs12(pfx_file=pfx_file, passphrase=passphrase.encode())

        # 2. Mở file PDF
        with open(input_pdf, 'rb') as inf:
            w = IncrementalPdfFileWriter(inf)

            # 3. Định nghĩa vị trí và Style
            box_position = (100, 100, 300, 150)

            stamp_style = TextStampStyle(
                stamp_text=f'Digital Signed by: {user_id}-{user_name}\nDate: %(ts)s',
                background=None,
                border_width=1
            )

            # 4. Tạo trường chữ ký
            fields.append_signature_field(
                w, 
                SigFieldSpec('SignatureVisible', box=box_position, on_page=0)
            )

            # 5. KHỞI TẠO OBJECT PdfSigner
            pdf_signer = signers.PdfSigner(
                signers.PdfSignatureMetadata(field_name='SignatureVisible'),
                signer=signer,
                stamp_style=stamp_style
            )

            # 6. Thực hiện ký
            with open(output_pdf, 'wb') as outf:
                pdf_signer.sign_pdf(w, output=outf)

        return jsonify({"message": "Đã ký file thành công", "output_pdf": output_pdf}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)