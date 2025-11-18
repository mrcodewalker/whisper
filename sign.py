import groupdocs.signature as gs
import groupdocs.signature.options as gso
import groupdocs.signature.domain as gsd

def add_form_field_signature():
   
    sample_pdf = "input.pdf"               # Tài liệu PDF nguồn của bạn
    output_file_path = "signed.pdf"    # Địa chỉ lưu tài liệu đã ký

    # Mở tài liệu để ký
    with gs.Signature(sample_pdf) as signature:
        # Tạo ký số trường văn bản với tên trường và giá trị mặc định
        # Tên trường là định danh, trong khi giá trị là văn bản mặc định
        text_signature = gs.domain.TextFormFieldSignature("SignatureField", "Nguyễn Quang Tùng")

        # Cấu hình tùy chọn trường biểu mẫu dựa trên ký số văn bản
        options = gso.FormFieldSignOptions(text_signature)

        # Đặt vị trí và kích thước của trường biểu mẫu ở góc dưới bên phải
        options.top = 750                   # Vị trí Y trên trang (gần cuối trang)
        options.left = 400                  # Vị trí X trên trang (gần mép phải)
        options.height = 50                 # Chiều cao của trường
        options.width = 200                 # Chiều rộng của trường

        # Ký tài liệu (thêm trường biểu mẫu) và lưu vào tệp
        result = signature.sign(output_file_path, options)

        # Hiển thị thông báo thành công với các mục nhật ký riêng biệt
        print(f"\nKý số trường biểu mẫu đã được thêm thành công.")
        print(f"Tổng số trường biểu mẫu đã thêm: {len(result.succeeded)}")
        print(f"Tệp được lưu tại {output_file_path}.")

if __name__ == "__main__":
    add_form_field_signature()
