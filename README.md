# JobHunterKit — AI-Powered CV Review & Tailoring Toolkit

> **Tự động hóa review, tối ưu hóa ATS và may đo CV theo từng Job Description bằng AI.**

---

## 📌 Giới thiệu (Overview)

`JobHunterKit` là bộ công cụ mã nguồn mở hỗ trợ ứng viên và người tìm việc:
1. **CV Review & ATS Audit**: Phân tích điểm mạnh, điểm yếu, phát hiện các lỗ hổng từ khóa (missing keywords) và rủi ro bị lọc bởi hệ thống ATS (Applicant Tracking System).
2. **May đo CV (CV Tailoring)**: Tự động điều chỉnh cấu trúc, từ khóa và câu mô tả kinh nghiệm (STAR / Google XYZ format) sát theo yêu cầu của từng Job Description (JD) mà không làm sai lệch sự thật.
3. **Xuất bản PDF chuẩn in ấn**: Tự động render bản HTML thành PDF vector độ phân giải cao bằng headless Playwright.

---

## 🚀 Hướng dẫn cài đặt nhanh (Quick Start)

### 1. Yêu cầu hệ thống
- Python 3.10 trở lên.
- Git.

### 2. Cài đặt môi trường

```bash
# Clone repository
git clone https://github.com/productaivn-wq/JobHunterKit.git
cd JobHunterKit

# Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt

# Cài đặt trình duyệt cho Playwright (để render PDF)
playwright install chromium
```

### 3. Cấu hình API Key

Tạo file `.env` từ file mẫu:

```bash
cp .env.example .env
```

Mở file `.env` và điền `GEMINI_API_KEY` (lấy miễn phí tại [Google AI Studio](https://aistudio.google.com/)):

```env
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.5-flash
```

---

## 🎯 Hướng dẫn sử dụng (Usage)

### 1. Review & Đánh giá CV tổng thể

Kiểm tra độ chuẩn hóa của CV theo tiêu chuẩn tuyển dụng và ATS:

```bash
python scripts/review_and_tailor_cv.py --cv "duong_dan/cv_cua_ban.pdf"
```

Lưu kết quả review ra file Markdown:

```bash
python scripts/review_and_tailor_cv.py --cv "duong_dan/cv_cua_ban.pdf" --output "danh_gia_cv.md"
```

### 2. So khớp CV với một Job Description (JD) cụ thể

Xem độ khớp giữa CV và JD mục tiêu, kèm theo các gợi ý sửa từng gạch đầu dòng:

```bash
python scripts/review_and_tailor_cv.py --cv "duong_dan/cv_cua_ban.pdf" --jd "duong_dan/jd.txt"
```

### 3. May đo CV & Xuất bản PDF mới theo JD

Tự động tinh chỉnh nội dung và xuất ra file PDF hoàn chỉnh:

```bash
python scripts/review_and_tailor_cv.py --cv "duong_dan/cv_cua_ban.pdf" --jd "duong_dan/jd.txt" --mode tailor --output "cv_da_chinh_sua.pdf"
```

---

## 📂 Cấu trúc thư mục (Directory Structure)

```
JobHunterKit/
├── config/
│   ├── applicant_profile.json.example   # Hồ sơ mẫu cho ứng viên
│   └── eval_rubric.json                 # Tiêu chí đánh giá ATS
├── core/                                # Core logic xử lý
├── scripts/
│   ├── review_and_tailor_cv.py          # Script chính cho Review & Tailor CV
│   ├── tailor_jd.py                     # Module render & may đo CV theo JD
│   ├── render_pdf.py                    # Module render HTML sang PDF
│   └── score_jd.py                      # Module chấm điểm chi tiết
├── shared_platform/                     # Kết nối LLM (Gemini API / Antigravity)
├── templates/
│   ├── resume_template.html             # Mẫu CV 1 cột hiện đại
│   └── cv_template.html                 # Mẫu CV tiêu chuẩn
├── .env.example                         # File cấu hình mẫu
├── requirements.txt                     # Danh sách thư viện Python
└── README.md
```

---

## 🛡️ Nguyên tắc May đo CV (Core Principles)
- **Zero Fabrication**: Không bịa đặt kinh nghiệm, công nghệ chưa từng làm hoặc chức danh ảo.
- **STAR / Action-Impact Formula**: Mỗi kinh nghiệm được cấu trúc theo dạng: *Hành động đã làm + Bối cảnh + Kết quả định lượng đo lường được*.
- **ATS Safe**: Bố cục rõ ràng, font chữ chuẩn hệ thống, không dùng bảng biểu phức tạp hay icon làm vỡ parser ATS.
