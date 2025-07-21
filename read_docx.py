import docx

def read_docx(file_path):
    try:
        doc = docx.Document(file_path)
        content = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                content.append(paragraph.text)
        return '\n'.join(content)
    except Exception as e:
        print(f"读取文件时出错: {e}")
        return None

if __name__ == "__main__":
    content = read_docx('多模态面试评测智能体实现_.docx')
    if content:
        print(content)
    else:
        print("无法读取文件内容") 