from __future__ import annotations

from app.pdf_store import Chunk


def build_messages(question: str, contexts: list[Chunk]) -> list[dict[str, str]]:
    context_block = "\n\n".join(
        f"[문서: {chunk.source_name} | 페이지: {chunk.page_number}]\n{chunk.content}"
        for chunk in contexts
    )

    system = (
        "너는 회사내규 질의응답 도우미입니다. 답변은 반드시 제공된 [Context] 정보만 근거로 작성해야 합니다. "
        "제공된 [Context] 정보만으로 질문에 답할 수 없다면, 절대 임의로 지어내거나 추측하지 말고 "
        "\"제공된 규정에서는 해당 내용을 찾을 수 없습니다.\"라고만 답변해야 합니다. "
        "질문에 답할 수 있는 경우에는 반드시 답변 문장 안에 근거가 된 문서명과 페이지 번호를 "
        "[문서명, p.페이지번호] 형식으로 명시해야 합니다. "
        "답변은 오직 한국어로만 작성해야 하며, 영어 문장, 사고 과정, 검토 과정, 중간 추론은 절대 출력해서는 안 됩니다."
    )
    user = (
        f"질문:\n{question}\n\n"
        f"참고 문맥:\n{context_block if context_block else '관련 문맥이 없습니다.'}\n\n"
        "출력 규칙:\n"
        "1. 가장 직접적인 규정 조항만 중심으로 설명한다.\n"
        "2. 질문과 직접 관련된 조항이 있으면 일반적인 근로계약 설명은 제외한다.\n"
        "3. 답변은 2~3문장 안으로 짧게 작성한다.\n"
        "4. 모든 답변 문장에는 반드시 근거 출처를 [문서명, p.페이지번호] 형식으로 포함한다.\n"
        "5. 참고 문맥에서 답을 찾을 수 없으면 반드시 \"제공된 규정에서는 해당 내용을 찾을 수 없습니다.\"라고만 답한다.\n"
        "6. 연차 일수 계산 질문에서는 질문한 근속연수에 해당하는 실제 휴가일수를 숫자로 답한다.\n"
        "7. '총 휴가일수는 25일 한도'는 최대치일 뿐 현재 연차일수로 단정하지 않는다.\n"
        "8. 여러 규정이나 문서를 함께 적용하는 질문이면 '수당:', '여비:', '경비:'처럼 항목별로 한국어만 사용해 정리한다.\n"
        "9. 'mentions that' 또는 'No, wait:'과 같은 영어 표현이나 내부 사고 과정은 절대 출력하지 않는다.\n"
        "10. 근거를 표시할 때만 문서명과 페이지 번호를 포함하고, 그 외의 파일명 설명은 덧붙이지 않는다."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
