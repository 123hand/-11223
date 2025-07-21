# xfyun_spark_client.py
import requests
import json
import logging

try:
    from config import SPARK_HTTP_API_PASSWORD, SPARK_MODEL_VERSION
except ImportError:
    logging.error("错误: 无法从 config.py 导入讯飞星火 HTTP API凭证和模型版本。")
    SPARK_HTTP_API_PASSWORD = "DEFAULT_X1_APIPASSWORD"
    SPARK_MODEL_VERSION = "x1"
    if SPARK_HTTP_API_PASSWORD == "DEFAULT_X1_APIPASSWORD":
        logging.critical("\n致命错误: config.py 中的 API 凭证未配置或配置有误。")
        logging.critical("请打开 config.py，将 'YOUR_X1_MODEL_APIPASSWORD_HERE' 替换为你的真实 APIPassword。")

class SparkClient:
    """
    讯飞星火大模型HTTP API客户端，仅支持APIpassword认证
    """
    def __init__(self, api_password, model_version="x1"):
        self.api_password = api_password
        self.model_version = model_version
        self.api_url = "https://spark-api-open.xf-yun.com/v2/chat/completions"
        logging.info(f"星火大模型客户端初始化完成，模型版本: {model_version}")
        self.messages = []

    def send_message(self, messages, max_retries=3):
        logging.error(f"进入Spark send_message，收到消息: {messages}")
        if not self.api_password:
            logging.error("API密码不能为空。请检查 config.py。")
            return None
        
        for attempt in range(max_retries):
            try:
                payload = {
                    "model": self.model_version,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 2048
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_password}"
                }

                logging.debug(f"使用Bearer Token认证，第{attempt+1}次尝试")
                logging.warning(f"发送到星火大模型的请求: {json.dumps(payload, ensure_ascii=False)}")
                
                # 添加重试和更长的超时时间
                response = requests.post(
                     self.api_url,
                     headers=headers,
                     json=payload,
                     timeout=90,  # 进一步增加超时时间
                     verify=True   # 确保SSL验证
                 )
                logging.debug(f"星火大模型原始响应: {response.text}")
                
                if response.status_code == 200:
                    result = response.json()
                    logging.debug(f"星火大模型响应: {json.dumps(result, ensure_ascii=False)}")
                    if "choices" in result and len(result["choices"]) > 0:
                        choice = result["choices"][0]
                        if "message" in choice and "content" in choice["message"]:
                            content = choice["message"]["content"]
                            logging.info(f"Spark send_message返回: {content}")
                            return content
                        else:
                            logging.error(f"星火大模型响应格式错误，缺少message或content字段: {choice}")
                            return None
                    else:
                        logging.error(f"星火大模型返回错误或格式不正确: {result}")
                        return None
                else:
                    logging.error(f"请求发生网络或HTTP错误: {response.status_code} {response.reason}")
                    logging.error(f"原始响应文本: {response.text}")
                    if attempt < max_retries - 1:
                        logging.info(f"等待2秒后重试...")
                        import time
                        time.sleep(2)
                        continue
                    return None
                    
            except requests.exceptions.Timeout as e:
                logging.error(f"请求超时 (第{attempt+1}次): {e}")
                if attempt < max_retries - 1:
                    logging.info(f"等待3秒后重试...")
                    import time
                    time.sleep(3)
                    continue
                return None
            except requests.exceptions.RequestException as e:
                logging.error(f"网络请求异常 (第{attempt+1}次): {e}")
                if attempt < max_retries - 1:
                    logging.info(f"等待2秒后重试...")
                    import time
                    time.sleep(2)
                    continue
                return None
            except json.JSONDecodeError as e:
                logging.error(f"JSON解析错误: {e}, 原始响应: {response.text if 'response' in locals() else '无'}")
                return None
            except Exception as e:
                logging.error(f"发送消息时发生未知错误: {e}")
                return None
        
        logging.error(f"所有{max_retries}次尝试都失败了")
        return None

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    client = SparkClient(
        api_password=SPARK_HTTP_API_PASSWORD,
        model_version=SPARK_MODEL_VERSION
    )
    conversation_history = [
        {"role": "user", "content": "你好，请你用面试官的身份给我提一个问题，关于Python编程的。"},
    ]
    print("开始模拟对话...")
    response = client.send_message(conversation_history)
    if response:
        print(f"\n面试官: {response}")
        conversation_history.append({"role": "assistant", "content": response})
        user_reply = "Python中GIL是全局解释器锁。它允许同一时刻只有一个线程执行Python字节码，即使在多核处理器上也是如此。这限制了Python在CPU密集型任务上的并行处理能力，但对于I/O密集型任务影响较小。"
        print(f"\n你的回答: {user_reply}")
        conversation_history.append({"role": "user", "content": user_reply})
        print("\n等待面试官的追问...")
        follow_up_response = client.send_message(conversation_history)
        if follow_up_response:
            print(f"\n面试官追问: {follow_up_response}")
        else:
            print("\n未能获取面试官的追问。")
    else:
        print("\n未能获取初始问题。")
    print("\n对话模拟结束。")