import logging
import os
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DIFY_TIMEOUT = 30

BOT_KEY_CONFIG = {
    "analysis": ("DIFY_ANALYSIS_API_KEY", "your_dify_analysis_chatbot_api_key_here", "종목 심층분석 챗봇"),
    "tech": ("DIFY_TECH_API_KEY", "your_dify_tech_chatbot_api_key_here", "지표해석기 챗봇"),
}


def ask_dify_chatbot(bot_type, query, inputs=None, context_text=None, conversation_id="", user_id="investment-user"):
    """Dify 챗봇(/v1/chat-messages)을 호출하여 답변과 conversation_id를 반환한다."""
    if bot_type not in BOT_KEY_CONFIG:
        return {"answer": None, "conversation_id": conversation_id, "error": f"알 수 없는 Dify 챗봇 유형입니다: {bot_type}"}

    env_name, placeholder, bot_label = BOT_KEY_CONFIG[bot_type]
    api_key = os.getenv(env_name, "").strip()

    if not api_key or api_key == placeholder or len(api_key) <= 5:
        logger.warning("[DIFY] %s API Key 미설정 (bot=%s)", bot_label, bot_type)
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": f"{bot_label} API Key({env_name})가 설정되지 않았습니다. .env 파일을 확인해 주세요.",
        }

    base_url = os.getenv("DIFY_API_BASE_URL", "https://api.dify.ai/v1").strip().rstrip("/")
    url = f"{base_url}/chat-messages"

    # Dify 기본 챗봇의 오케스트레이트 변수 미설정 시에도 근거를 읽을 수 있도록 query에 컨텍스트 안전 결합
    final_query = query.strip() if query else "분석해 주세요."
    if context_text:
        final_query = f"[분석 근거 데이터]\n{context_text}\n\n[사용자 질문]\n{final_query}"

    payload = {
        "inputs": inputs or {},
        "query": final_query,
        "response_mode": "blocking",
        "conversation_id": conversation_id or "",
        "user": user_id,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info("[DIFY] Dify 챗봇 API 호출 시작 (bot=%s, has_conv_id=%s)", bot_type, bool(conversation_id))

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=DIFY_TIMEOUT)
    except requests.Timeout:
        logger.error("[ERROR] Dify 챗봇 API 타임아웃 (bot=%s)", bot_type, exc_info=True)
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": "Dify 챗봇 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
        }
    except requests.RequestException as e:
        logger.error("[ERROR] Dify 챗봇 API 연결 실패 (bot=%s): %s", bot_type, e, exc_info=True)
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": "Dify 챗봇 서버에 연결하지 못했습니다.",
        }

    if resp.status_code in (401, 403):
        logger.error("[ERROR] Dify 챗봇 인증 실패 (bot=%s, status=%s)", bot_type, resp.status_code)
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": f"{bot_label} API 인증에 실패했습니다. .env의 {env_name} 값을 확인해 주세요.",
        }

    if resp.status_code != 200:
        logger.error("[ERROR] Dify 챗봇 API 오류 (bot=%s, status=%s, body=%s)", bot_type, resp.status_code, resp.text[:300])
        detail_msg = ""
        try:
            err_json = resp.json()
            if err_json.get("message"):
                detail_msg = f" - {err_json['message']}"
        except ValueError:
            pass
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": f"{bot_label} 응답 오류가 발생했습니다 (상태 코드: {resp.status_code}{detail_msg}).",
        }

    try:
        data = resp.json()
    except ValueError:
        logger.error("[ERROR] Dify 챗봇 응답 JSON 변환 실패 (bot=%s)", bot_type, exc_info=True)
        return {
            "answer": None,
            "conversation_id": conversation_id,
            "error": "Dify 챗봇 응답 데이터를 JSON으로 변환하는 데 실패했습니다.",
        }

    answer = data.get("answer")
    new_conv_id = data.get("conversation_id", conversation_id)

    if not answer:
        return {
            "answer": None,
            "conversation_id": new_conv_id,
            "error": "Dify 챗봇으로부터 빈 응답을 받았습니다.",
        }

    logger.info("[DIFY] Dify 챗봇 API 호출 완료 (bot=%s, answer_len=%d)", bot_type, len(answer))
    return {
        "answer": answer,
        "conversation_id": new_conv_id,
        "error": None,
    }
