import csv
from langchain_core.documents import Document


def load_jargon_dict(path: str) -> list[Document]:
    """加载 jargon_dict.csv，每行作为一个 Document"""
    docs = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            text = f"{row['keyword']}：{row['real_meaning']}"
            metadata = {
                "keyword": row.get("keyword", ""),
                "source": "jargon_dict",
            }
            docs.append(Document(page_content=text, metadata=metadata))
    return docs
