import wave
import librosa
import numpy as np
import logging
import os
import struct # 导入 struct 模块用于处理字节数据

# 注意：这里移除 logging.basicConfig，由 app.py 统一配置

class VoiceAnalyzer:
    def __init__(self, sample_rate=16000, channels=1, sample_width=2): # sample_width=2 对应 paInt16
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        logging.info("VoiceAnalyzer 初始化完成。")

    def save_audio(self, audio_frames, filename="temp_interview_audio.wav"):
        """
        将 PyAudio 捕获的音频帧保存为 WAV 文件。
        audio_frames: 一个包含字节串的列表，每个字节串是一个音频块。
        filename: 保存 WAV 文件的路径。
        """
        if not audio_frames:
            logging.warning("没有可保存的音频帧。")
            print("【语音分析】警告：没有可保存的音频帧")
            return None

        # 确保目录存在
        output_dir = "audio_records"
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, filename)

        try:
            # 计算总音频数据大小
            total_size = sum(len(frame) for frame in audio_frames)
            print(f"【语音分析】准备保存音频文件，总大小: {total_size} 字节，帧数: {len(audio_frames)}")
            
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.sample_width)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(audio_frames))
            
            # 检查文件是否成功创建
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                print(f"【语音分析】音频文件保存成功: {file_path}, 文件大小: {file_size} 字节")
                logging.info(f"音频已保存到: {file_path}, 大小: {file_size} 字节")
                return file_path
            else:
                print(f"【语音分析】错误：文件保存失败，文件不存在: {file_path}")
                return None
        except Exception as e:
            logging.error(f"保存音频文件失败: {e}", exc_info=True)
            print(f"【语音分析】保存音频文件异常: {e}")
            return None

    def analyze_audio_features(self, audio_path):
        """
        快速分析WAV音频文件的语音特征。
        优化版本：只计算核心特征，避免耗时的音高检测。
        """
        if not os.path.exists(audio_path):
            logging.error(f"音频文件不存在: {audio_path}")
            print(f"【语音分析】错误：音频文件不存在: {audio_path}")
            return None

        try:
            print(f"【语音分析】开始快速分析音频文件: {audio_path}")
            
            # 快速加载音频文件（不重采样）
            y, sr = librosa.load(audio_path, sr=None)  # 保持原始采样率
            print(f"【语音分析】音频加载成功，采样率: {sr}, 长度: {len(y)} 样本")

            # 1. 快速计算响度 (RMS)
            # 直接计算，不使用librosa.feature.rms()避免额外开销
            rms = np.sqrt(np.mean(y**2))
            print(f"【语音分析】平均 RMS: {rms:.6f}")

            # 转换为分贝
            db_level = 20 * np.log10(rms + 1e-10)  # 避免log(0)
            print(f"【语音分析】平均响度 (dB): {db_level:.2f}")

            # 2. 计算时长
            duration = len(y) / sr
            print(f"【语音分析】音频时长: {duration:.2f} 秒")
            
            # 3. 简化的音高估算（基于频谱峰值，比estimate_tuning快很多）
            # 使用FFT快速估算主要频率成分
            if len(y) > 1024:  # 确保有足够的数据
                # 取中间部分进行分析，避免边界效应
                mid_start = len(y) // 4
                mid_end = 3 * len(y) // 4
                y_mid = y[mid_start:mid_end]
                
                # 快速FFT分析
                fft = np.fft.fft(y_mid)
                freqs = np.fft.fftfreq(len(y_mid), 1/sr)
                
                # 只分析正频率部分
                pos_freqs = freqs[:len(freqs)//2]
                pos_fft = np.abs(fft[:len(fft)//2])
                
                # 找到主要频率成分（排除直流分量）
                # 只考虑60-600Hz范围（人声主要频率范围）
                voice_mask = (pos_freqs >= 60) & (pos_freqs <= 600)
                if np.any(voice_mask):
                    voice_freqs = pos_freqs[voice_mask]
                    voice_fft = pos_fft[voice_mask]
                    
                    # 找到最大幅度的频率
                    max_idx = np.argmax(voice_fft)
                    avg_f0 = voice_freqs[max_idx]
                else:
                    avg_f0 = 0
            else:
                avg_f0 = 0
            
            print(f"【语音分析】估算音高: {avg_f0:.2f} Hz")
            
            # 4. 简化的情绪判断
            emotional_tone = "中性"
            if db_level > -20 and avg_f0 > 150:  # 响度较高且音高较高
                emotional_tone = "积极"
            elif db_level < -40 or avg_f0 < 80:   # 响度很低或音高很低
                emotional_tone = "平静"

            result = {
                "loudness_db": float(db_level),
                "duration_seconds": float(duration),
                "average_pitch_hz": float(avg_f0),
                "estimated_emotional_tone": emotional_tone
            }
            
            print(f"【语音分析】快速分析完成，结果: {result}")
            return result
            
        except Exception as e:
            logging.error(f"快速分析音频特征失败: {e}", exc_info=True)
            print(f"【语音分析】快速分析音频特征异常: {e}")
            return None
    
    # 修正后的 calculate_audio_features 方法
    def calculate_audio_features(self, audio_data):
        """
        处理单个实时音频块，计算其RMS和分贝。
        注意：音高和语速通常需要更长的音频序列来准确计算。
        这里只返回 RMS 和 current_db，对于 pitch 和 speaking_rate 返回默认值。
        """
        if not audio_data:
            logging.warning("传入的 audio_data 为空。")
            return 0, -np.inf, 0, 0 # 返回默认值

        try:
            # 将字节数据转换为 NumPy 数组 (int16)
            audio_np = np.frombuffer(audio_data, dtype=np.int16)

            if len(audio_np) == 0:
                logging.warning("转换后的 audio_np 数组为空。")
                return 0, -np.inf, 0, 0 # 返回默认值

            # 计算 RMS - 使用更安全的计算方法
            audio_squared = audio_np.astype(np.float64) ** 2  # 转换为float64避免溢出
            rms = np.sqrt(np.mean(audio_squared))

            # 将 RMS 转换为分贝
            if rms == 0:
                current_db = -np.inf
            else:
                # 使用最大可能幅度作为参考，对于 int16 为 32767
                current_db = 20 * np.log10(rms / 32767.0) 

            # logging.debug(f"RMS: {rms:.2f}, Current dB: {current_db:.2f}")  # 注释掉RMS调试信息，避免刷屏

            # 对于实时音频块，精确的音高和语速计算较为复杂且可能不准确。
            # 如果需要，这里可以尝试更高级的实时特征提取库。
            # 目前先返回默认值。
            pitch = 0  # 实时音高计算需要更多上下文
            speaking_rate = 0 # 实时语速计算需要 ASR 文本结果

            return rms, current_db, pitch, speaking_rate

        except Exception as e:
            logging.error(f"实时音频特征计算失败: {e}", exc_info=True)
            return 0, -np.inf, 0, 0 # 发生错误时返回默认值

    def is_speaking(self, audio_chunk, threshold_db=-40):
        """
        判断音频块是否包含有效语音（基于响度）。
        audio_chunk: 原始字节流音频块。
        threshold_db: 分贝阈值，高于此阈值认为是语音。
        """
        if not audio_chunk:
            return False # 如果音频块为空，直接返回不是语音

        try:
            # 将字节数据转换为 NumPy 数组 (假设是 int16)
            # 使用 np.frombuffer 确保数据类型正确
            audio_np = np.frombuffer(audio_chunk, dtype=np.int16)

            if audio_np.size == 0: # 检查数组是否为空
                return False

            # 避免在全零或极小值时出现 RuntimeWarning
            # 使用更安全的计算方法
            audio_squared = audio_np.astype(np.float64) ** 2  # 转换为float64避免溢出
            rms = np.sqrt(np.mean(audio_squared) + 1e-10) # 加上一个非常小的数避免0

            # 将 RMS 转换为分贝 (dB)
            # 参考标准声压级为最大可能的振幅值 (对于 int16 是 32767)
            # 计算方式：20 * log10(RMS / 参考振幅)
            # 这里简化为相对于最大可能值的 dBFS (dB Full Scale)
            if rms == 0: # 如果 RMS 仍然为 0，分贝应为负无穷，直接返回 False
                return False

            # 使用 int16 的最大值作为参考（2^15 - 1）
            max_amplitude = np.iinfo(np.int16).max
            db = 20 * np.log10(rms / max_amplitude)

            # logging.debug(f"RMS: {rms:.2f}, dB: {db:.2f}, Threshold: {threshold_db}")
            return db > threshold_db
        except Exception as e:
            logging.error(f"语音分析错误: {e}", exc_info=True)
            return False


# --- 示例使用 (仅用于测试 voice_analyzer.py 自身的功能) ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    analyzer = VoiceAnalyzer()

    # 测试 is_speaking 方法
    print("测试 is_speaking:")
    # 模拟静音数据 (全0字节)
    silence_chunk = b'\x00' * 1024 # 1024 字节 = 512 个 int16 样本
    print(f"静音数据检测 (阈值 -30dB): {analyzer.is_speaking(silence_chunk, threshold_db=-30)}")
    print(f"静音数据检测 (阈值 -80dB): {analyzer.is_speaking(silence_chunk, threshold_db=-80)}")


    # 模拟一些噪音数据 (随机字节，可能高于静音)
    # 模拟一个非常小的随机信号，大概率低于阈值
    noise_chunk = np.random.randint(-100, 100, size=1024, dtype=np.int16).tobytes()
    print(f"噪音数据检测 (阈值 -30dB): {analyzer.is_speaking(noise_chunk, threshold_db=-30)}")
    print(f"噪音数据检测 (阈值 -80dB): {analyzer.is_speaking(noise_chunk, threshold_db=-80)}")

    # 模拟一个较大的声音 (随机高振幅数据)
    high_amplitude_chunk = np.random.randint(-20000, 20000, size=1024, dtype=np.int16).tobytes()
    print(f"高振幅数据检测 (阈值 -30dB): {analyzer.is_speaking(high_amplitude_chunk, threshold_db=-30)}")
    print(f"高振幅数据检测 (阈值 -80dB): {analyzer.is_speaking(high_amplitude_chunk, threshold_db=-80)}")


    # 测试保存和分析功能
    print("\n测试音频保存和特征分析:")
    test_audio_data_for_save = (np.random.randint(-5000, 5000, size=16000 * 2, dtype=np.int16)).tobytes() # 2秒钟的随机音频
    test_audio_frames = [test_audio_data_for_save[i:i+1024] for i in range(0, len(test_audio_data_for_save), 1024)]

    saved_file = analyzer.save_audio(test_audio_frames, filename="test_audio_for_analysis.wav")

    if saved_file:
        features = analyzer.analyze_audio_features(saved_file)
        if features:
            print("\n分析结果:")
            for key, value in features.items():
                print(f"- {key}: {value}")
        else:
            print("音频特征分析失败。")
    else:
        print("音频保存失败，无法进行分析。")
        
    # 测试实时音频特征计算
    print("\n测试实时音频特征计算:")
    # 模拟一段有声音的实时音频数据
    live_audio_data = (np.random.randint(-10000, 10000, size=1600, dtype=np.int16)).tobytes() # 100ms 的数据
    rms, current_db, pitch, speaking_rate = analyzer.calculate_audio_features(live_audio_data)
    print(f"实时特征 - RMS: {rms:.2f}, DB: {current_db:.2f}, Pitch: {pitch:.2f}, Speaking Rate: {speaking_rate:.2f}")


    # 清理测试文件
    if saved_file and os.path.exists(saved_file):
        # os.remove(saved_file) # 调试时可以暂时不删除
        print(f"\n清理测试文件: {saved_file}")