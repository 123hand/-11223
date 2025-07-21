from flask import Flask, request, jsonify, current_app
from xfyun_spark_client import SparkClient
import json

# 讯飞API密码和模型版本（确保 config.py 里配置正确）
from config import SPARK_HTTP_API_PASSWORD, SPARK_MODEL_VERSION

def interview_evaluation():
    # 前端传来的面试对话内容
    data = request.get_json()
    print('收到 video_analysis:', data.get('video_analysis'))
    print('收到 resume_text:', data.get('resume_text'))
    # 新增：支持直接读取 history 字段
    history = data.get('history')
    if history and isinstance(history, list) and len(history) > 0:
        # 自动拼接为 interview_text
        interview_text = ''
        for idx, item in enumerate(history):
            q = item.get('question', '')
            a = item.get('answer', '')
            interview_text += f"第{idx+1}题\n面试官：{q}\n候选人：{a if a else '未回答'}\n"
    else:
        interview_text = data.get('interview_text', '')
    
    # 直接使用data['audio_analysis']，不再从app_server导入all_round_audio_analysis
    audio_analysis = data.get('audio_analysis', '无语音分析数据')
    print(f"【语音分析】最终分析文本: {audio_analysis}")
    
    video_analysis = data.get('video_analysis', '无')  # 预留：前端可传视频分析
    resume_text = data.get('resume_text', '无')        # 预留：前端可传简历

    # 如果没有面试内容，生成默认的评测报告
    if not interview_text or interview_text.strip() == '':
        # 返回默认的评测报告，表示候选人没有参与面试
        default_report = {
            "scores": {
                "专业知识水平": 0,
                "技能匹配度": 0,
                "语言表达能力": 0,
                "逻辑思维能力": 0,
                "创新能力": 0,
                "应变抗压能力": 0
            },
            "radar": [0, 0, 0, 0, 0, 0],
            "key_issues": [
                {"question": "面试参与度", "issue": "候选人未参与面试或未提供有效回答"}
            ],
            "suggestions": [
                "建议候选人积极参与面试",
                "准备自我介绍和项目经验",
                "练习语言表达和逻辑思维"
            ],
            "multimodal_analysis": {
                "audio": "无语音数据",
                "video": "无视频数据",
                "text": "无文本回答内容",
                "resume": "无简历数据"
            },
            "summary": "候选人未参与面试，无法进行有效评测。建议重新安排面试或检查系统设置。"
        }
        return jsonify(default_report)

    # 对面试内容进行去重处理
    def remove_duplicates(text):
        """去除重复内容，保留最长的完整版本"""
        lines = text.split('\n')
        cleaned_lines = []
        seen_content = set()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 检查是否是重复内容
            is_duplicate = False
            for seen in seen_content:
                if line in seen or seen in line:
                    is_duplicate = True
                    # 如果当前行更长，替换已存在的内容
                    if len(line) > len(seen):
                        seen_content.remove(seen)
                        seen_content.add(line)
                    break
            
            if not is_duplicate:
                seen_content.add(line)
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    # 对面试文本进行去重
    cleaned_interview_text = remove_duplicates(interview_text)
    print('cleaned_interview_text:', cleaned_interview_text)

    # 构造多模态评测prompt
    prompt = (
        "你是一个多模态智能面试评测专家。请根据以下四类面试数据，"
        "生成结构化、可视化友好的评测反馈报告，内容包括：\n"
        "1. 能力雷达图数据（六大维度0-100分，JSON数组）；\n"
        "2. 关键问题定位（每个问题包含：问题内容、定位原因、改进建议）；\n"
        "3. 针对每个能力维度的具体改进建议；\n"
        "4. 多模态分析（请分别引用和分析下方的问答内容、语音分析、视频分析、简历内容）；\n"
        "5. 总结（简明扼要的整体评价和建议）。\n"
        "请严格输出如下JSON格式：\n"
        "{\n"
        "\"scores\": {\"专业知识水平\": 85, \"技能匹配度\": 80, \"语言表达能力\": 90, \"逻辑思维能力\": 88, \"创新能力\": 75, \"应变抗压能力\": 82},\n"
        "\"radar\": [85, 80, 90, 88, 75, 82],\n"
        "\"key_issues\": [\n"
        "  {\"question\": \"请介绍你的项目经验\", \"reason\": \"缺乏具体量化成果\", \"suggestion\": \"建议补充项目中的具体数据和成果\"},\n"
        "  {\"question\": \"请描述一次压力下的决策\", \"reason\": \"应变能力表现一般\", \"suggestion\": \"建议举例说明如何在压力下做出有效决策\"}\n"
        "],\n"
        "\"suggestions\": [\n"
        "  \"多用数据和案例支撑观点\",\n"
        "  \"提升创新思维表达\",\n"
        "  \"注意眼神交流和肢体语言\"\n"
        "],\n"
        "\"multimodal_analysis\": {\n"
        "  \"text\": \"请详细分析上方问答内容，评价文本表达和内容质量。\",\n"
        "  \"audio\": \"请详细分析下方 audio_analysis 字段内容，评价语音表现。\",\n"
        "  \"video\": \"请详细分析下方 video_analysis 字段内容，评价视频表现。\",\n"
        "  \"resume\": \"请详细分析下方 resume_text 字段内容，评价简历表现。\"\n"
        "},\n"
        "\"summary\": \"总体评价和建议\"\n"
        "}\n"
        "请严格只输出JSON，不要有多余解释。\n"
        "面试数据如下：\n"
        "【问答内容】：\n" + cleaned_interview_text + "\n"
        "【语音分析】：" + audio_analysis + "\n"
        "【视频分析】：" + video_analysis + "\n"
        "【简历内容】：" + resume_text
    )

    messages = [{"role": "user", "content": prompt}]
    
    try:
        client = SparkClient(api_password=SPARK_HTTP_API_PASSWORD, model_version=SPARK_MODEL_VERSION)
        print(f"调用Spark API，prompt长度: {len(prompt)}")
        # 调用Spark API（send_message方法已经内置了重试机制）
        ai_response = client.send_message(messages)
        print(f"AI原始返回内容: {ai_response}")
        
        # 解析AI返回的JSON
        try:
            result = json.loads(ai_response)
            return jsonify(result)
        except Exception as e:
            print(f"JSON解析失败: {e}")
            # 尝试用正则提取大括号包裹的JSON
            import re
            match = re.search(r'\{[\s\S]*\}', ai_response)
            if match:
                try:
                    extracted_json = match.group(0)
                    print(f"提取的JSON: {extracted_json}")
                    result = json.loads(extracted_json)
                    return jsonify(result)
                except Exception as e2:
                    print(f"提取JSON解析也失败: {e2}")
                    pass
            return jsonify({'error': 'AI返回内容解析失败', 'raw': ai_response[:500]}), 500
            
    except Exception as e:
        print(f"Spark API调用失败: {e}")
        # 当AI调用失败时，返回基于面试内容的简单评测
        try:
            # 分析面试内容，生成简单报告
            has_answers = "候选人：" in cleaned_interview_text and not all("未回答" in line for line in cleaned_interview_text.split('\n') if "候选人：" in line)
            
            if has_answers:
                # 有回答但AI调用失败，返回基础报告
                fallback_report = {
                    "scores": {
                        "专业知识水平": 50,
                        "技能匹配度": 50,
                        "语言表达能力": 50,
                        "逻辑思维能力": 50,
                        "创新能力": 50,
                        "应变抗压能力": 50
                    },
                    "radar": [50, 50, 50, 50, 50, 50],
                    "key_issues": [
                        {"question": "系统评测", "issue": "AI服务暂时不可用，无法进行详细评测"}
                    ],
                    "suggestions": [
                        "建议重新生成报告",
                        "检查网络连接",
                        "联系技术支持"
                    ],
                    "multimodal_analysis": {
                        "audio": "无语音分析数据",
                        "video": "无视频分析数据",
                        "text": "检测到面试回答内容，但无法进行AI深度分析",
                        "resume": "无简历数据"
                    },
                    "summary": "系统检测到面试内容，但AI服务暂时不可用。建议稍后重新生成报告或联系技术支持。"
                }
            else:
                # 没有回答，返回默认报告
                fallback_report = {
                    "scores": {
                        "专业知识水平": 0,
                        "技能匹配度": 0,
                        "语言表达能力": 0,
                        "逻辑思维能力": 0,
                        "创新能力": 0,
                        "应变抗压能力": 0
                    },
                    "radar": [0, 0, 0, 0, 0, 0],
                    "key_issues": [
                        {"question": "面试参与度", "issue": "候选人未参与面试或未提供有效回答"}
                    ],
                    "suggestions": [
                        "建议候选人积极参与面试",
                        "准备自我介绍和项目经验",
                        "练习语言表达和逻辑思维"
                    ],
                    "multimodal_analysis": {
                        "audio": "无语音数据",
                        "video": "无视频数据",
                        "text": "无文本回答内容",
                        "resume": "无简历数据"
                    },
                    "summary": "候选人未参与面试，无法进行有效评测。建议重新安排面试或检查系统设置。"
                }
            return jsonify(fallback_report)
        except Exception as fallback_error:
            print(f"生成备用报告也失败: {fallback_error}")
            return jsonify({'error': f'AI服务调用失败: {str(e)}'}), 500
