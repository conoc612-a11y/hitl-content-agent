import streamlit as st

from pipeline import approve, load_pending, process_request, read_jsonl, reject, stats
from pipeline import PUBLISHED_FILE, REJECTED_FILE


st.set_page_config(page_title="HITL 콘텐츠 발행 에이전트", layout="wide")

st.title("HITL 콘텐츠 발행 에이전트")
st.caption("뉴스레터, 블로그, 마케팅 문구, SNS 글을 자동 생성하되 위험한 글은 발행 직전에 멈춥니다.")

with st.expander("이 에이전트는 어디에 쓰나요?", expanded=True):
    st.markdown(
        """
        - 뉴스레터를 구독자에게 보내기 전 검수
        - 블로그 글을 공개 발행하기 전 승인
        - 마케팅 문구를 캠페인 페이지에 올리기 전 승인
        - SNS 글을 예약 발행하기 전 승인

        이 데모에서는 실제 외부 발송 대신 `data/published.jsonl`에 저장하는 것으로 발행을 모의합니다.
        """
    )

counts = stats()
col1, col2, col3 = st.columns(3)
col1.metric("승인 대기", counts["pending"])
col2.metric("발행 완료", counts["published"])
col3.metric("반려", counts["rejected"])

tab_new, tab_pending, tab_history = st.tabs(["새 요청 처리", "승인 대기", "처리 기록"])

with tab_new:
    st.subheader("콘텐츠 요청 입력")
    sample = "신규 기능 업데이트 안내. 사용자는 설정 화면에서 알림을 켤 수 있습니다."
    request_text = st.text_area("요청 원문", value=sample, height=140)
    if st.button("에이전트 실행", type="primary"):
        if request_text.strip():
            result = process_request(request_text)
            if result["status"] == "pending":
                st.warning("승인 기준에 걸려 발행 직전에 멈췄습니다.")
            else:
                st.success("승인 없이 자동 발행되었습니다.")
            st.json(result)
        else:
            st.error("요청 원문을 입력하세요.")

with tab_pending:
    st.subheader("승인 대기 목록")
    pending = load_pending()
    if not pending:
        st.info("승인 대기 건이 없습니다.")
    else:
        labels = [f"{item['id']} | 점수 {item['review']['quality_score']} | {item['request_text'][:35]}" for item in pending]
        selected_label = st.selectbox("검토할 건", labels)
        item = pending[labels.index(selected_label)]

        left, right = st.columns(2)
        with left:
            st.markdown("#### 요청 원문")
            st.write(item["request_text"])
            st.markdown("#### 에이전트 초안")
            st.text_area("초안", value=item["draft"], height=260, disabled=True, label_visibility="collapsed")
        with right:
            st.markdown("#### 에이전트 판단과 근거")
            st.write(f"검수 점수: {item['review']['quality_score']}")
            st.write("승인 필요 여부: 예")
            st.markdown("#### 멈춘 이유")
            for reason in item["review"]["reasons"]:
                st.warning(reason)
            st.markdown("#### 승인하면 일어나는 일")
            st.info(item["resume_action"])

        note = st.text_input("검토 메모")
        approve_col, reject_col = st.columns(2)
        if approve_col.button("승인", type="primary"):
            approve(item["id"], note)
            st.success("승인되어 발행 완료 기록으로 이동했습니다.")
            st.rerun()
        if reject_col.button("반려"):
            reject(item["id"], note)
            st.success("반려 기록으로 이동했습니다.")
            st.rerun()

with tab_history:
    st.subheader("발행 완료")
    st.dataframe(read_jsonl(PUBLISHED_FILE), use_container_width=True)
    st.subheader("반려")
    st.dataframe(read_jsonl(REJECTED_FILE), use_container_width=True)
