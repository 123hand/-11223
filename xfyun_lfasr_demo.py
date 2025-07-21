import requests
import hashlib
import hmac
import base64
import time
import json
import os

class XfyunFileASRClient:
    def __init__(self, appid, secret_key, upload_url, get_result_url):
        self.appid = appid
        self.secret_key = secret_key
        self.upload_url = upload_url
        self.get_result_url = get_result_url

    def get_signa(self, ts):
        base_string = self.appid + str(ts)
        md5 = hashlib.md5()
        md5.update(base_string.encode('utf-8'))
        md5_str = md5.hexdigest()
        signa = hmac.new(self.secret_key.encode('utf-8'), md5_str.encode('utf-8'), digestmod='sha1').digest()
        signa = base64.b64encode(signa).decode('utf-8')
        return signa

    def upload_audio(self, file_path, language="cn"):
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        ts = int(time.time())
        signa = self.get_signa(ts)
        data = {
            "appId": self.appid,
            "signa": signa,
            "ts": ts,
            "fileSize": file_size,
            "fileName": file_name,
            "language": language
        }
        # 正确用法：用with打开文件，传递文件对象给files参数
        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, "audio/wav")}
                response = requests.post(self.upload_url, data=data, files=files)
            res = response.json()
            if res.get("code") == "0" and "orderId" in res:
                print(f"上传成功，orderId: {res['orderId']}")
                return res["orderId"]
            else:
                print(f"上传失败: {res}")
                return None
        except Exception as e:
            print(f"上传异常: {e}")
            return None

    def get_result(self, order_id):
        ts = int(time.time())
        signa = self.get_signa(ts)
        data = {
            "appId": self.appid,
            "signa": signa,
            "ts": ts,
            "orderId": order_id
        }
        for _ in range(60):  # 最多轮询60次
            try:
                response = requests.post(self.get_result_url, data=data)
                res = response.json()
                if res.get("code") == "0" and res.get("data") and res["data"].get("status") == 4:
                    # status=4表示转写完成
                    result = res["data"].get("result", "")
                    print(f"转写完成: {result}")
                    return result
                elif res.get("code") == "0":
                    time.sleep(2)
                    continue
                else:
                    print(f"转写失败: {res}")
                    return None
            except Exception as e:
                print(f"查询异常: {e}")
                return None
        print("转写超时")
        return None

# 兼容原有脚本用法
if __name__ == "__main__":
    APPID = "dde81f6b"
    SECRET_KEY = "ab25515bb7692a0790ef5a566342d5d7"
    UPLOAD_URL = "https://raasr.xfyun.cn/v2/api/upload"
    GET_RESULT_URL = "https://raasr.xfyun.cn/v2/api/getResult"
    client = XfyunFileASRClient(APPID, SECRET_KEY, UPLOAD_URL, GET_RESULT_URL)
    order_id = client.upload_audio("test.mp3", language="cn")  # 这里替换为你的音频文件路径
    if order_id:
        client.get_result(order_id)
