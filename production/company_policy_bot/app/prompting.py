from __future__ import annotations

from app.pdf_store import Chunk


def build_messages(question: str, contexts: list[Chunk]) -> list[dict[str, str]]:
    context_block = "\n\n".join(
        f"[문서: {chunk.source_name} | 페이지: {chunk.page_number}]\n{chunk.content}"
        for chunk in contexts
    )

    system = (
        "너는 회사내규 질의응답 도우미입니다. 사용자에게 친절하고 정중하게 답변해주세요. "
        "반드시 제공된 PDF 근거만 바탕으로 답변하고, 근거가 부족하면 추측하지 말고 모른다고 말해주십시오. "
        "답변은 오직 한국어로만 작성해야 하며, 어떠한 영어 문장, 사고 과정, 검토 과정, 중간 추론도 절대 출력해서는 안 됩니다."
    )
    user = (
        f"질문:\n{question}\n\n"
        f"참고 문맥:\n{context_block if context_block else '관련 문맥이 없습니다.'}\n\n"
        "출력 규칙:\n"
        "1. 가장 직접적인 규정 조항만 중심으로 설명한다.\n"
        "2. 질문과 직접 관련된 조항이 있으면 일반적인 근로계약 설명은 제외한다.\n"
        "3. 답변은 2~3문장 안으로 짧게 작성한다.\n"
        "4. '참고:' 문구는 쓰지 않는다. 참고 문서 표시는 시스템이 별도로 붙인다.\n"
        "5. 참고 문맥에서 답을 찾을 수 없으면 모른다고 말한다.\n"
        "6. 연차 일수 계산 질문에서는 질문한 근속연수에 해당하는 실제 휴가일수를 숫자로 답한다.\n"
        "7. '총 휴가일수는 25일 한도'는 최대치일 뿐 현재 연차일수로 단정하지 않는다.\n"
        "8. 여러 규정이나 문서를 함께 적용하는 질문이면 '수당:', '여비:', '경비:'처럼 항목별로 한국어만 사용해 정리한다.\n"
        "9. 'mentions that' 또는 'No, wait:'과 같은 영어 표현이나 내부 사고 과정은 절대 출력하지 않는다.\n"
        "10. 파일명, 페이지 설명 등은 답변 내용에 포함하지 않는다."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
