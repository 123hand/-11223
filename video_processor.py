import cv2
import time
import logging
import os
import threading
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class VideoProcessor:
    def __init__(self, camera_index=0, output_dir="video_records", fps=30, resolution=(640, 480)):
        self.camera_index = camera_index
        self.output_dir = output_dir
        self.fps = fps
        self.resolution = resolution
        self.cap = None  # 摄像头对象
        self.video_writer = None  # 视频写入对象
        self.is_recording = False
        self.recording_thread = None
        self.frames_buffer = []  # 缓存帧，用于写入视频文件
        self.lock = threading.Lock() # 用于保护 frames_buffer 的锁
        self.thread_stop_event = threading.Event() # 用于通知写入线程停止

        os.makedirs(self.output_dir, exist_ok=True)

    def start_camera(self):
        """
        尝试开启摄像头。
        返回 True 如果成功开启，否则 False。
        """
        if self.cap and self.cap.isOpened():
            logging.info("摄像头已开启。")
            return True

        # 使用 CAP_DSHOW 提高 Windows 兼容性
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            logging.error(f"无法打开摄像头 (索引: {self.camera_index})。请检查摄像头是否连接或被占用。")
            self.cap = None
            return False

        # 尝试设置分辨率和帧率
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        # 实际获取设置后的分辨率和帧率
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        logging.info(f"摄像头 {self.camera_index} 已开启，实际分辨率: ({actual_width}, {actual_height}), 实际帧率: {actual_fps:.2f} FPS。")
        self.resolution = (actual_width, actual_height) # 更新为实际分辨率
        self.fps = actual_fps # 更新为实际帧率

        return True

    def capture_frame(self):
        """
        从摄像头捕获一帧。
        返回捕获到的帧 (numpy.ndarray) 或 None。
        """
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                return frame
            else:
                logging.warning("无法读取摄像头帧。")
                return None
        else:
            # logging.warning("摄像头未开启，无法捕获帧。")
            return None

    def add_frame_to_buffer(self, frame):
        """
        将捕获到的帧添加到缓冲区。
        """
        with self.lock:
            self.frames_buffer.append(frame)

    def _write_frames_to_video(self, filename):
        """
        内部方法：负责将缓冲区中的帧写入视频文件。
        在新线程中运行。
        """
        file_path = os.path.join(self.output_dir, filename)
        
        # 定义视频编码器和 VideoWriter
        # FourCC 是视频编解码器的4字符代码。'mp4v' 是 MPEG-4 编码。
        # 对于 Windows，可以尝试 DIVX, XVID, MJPG, H264 等
        # 对于跨平台兼容性，MP4V 或 H264 是不错的选择
        fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
        
        try:
            self.video_writer = cv2.VideoWriter(file_path, fourcc, self.fps, self.resolution)
            if not self.video_writer.isOpened():
                logging.error(f"无法创建视频写入器或打开视频文件: {file_path}")
                self.is_recording = False
                self.thread_stop_event.set() # 写入失败，停止线程
                return

            logging.info(f"开始写入视频文件: {file_path}, 分辨率: {self.resolution}, 帧率: {self.fps}")

            while not self.thread_stop_event.is_set() or len(self.frames_buffer) > 0:
                with self.lock:
                    if self.frames_buffer:
                        frame = self.frames_buffer.pop(0)
                        self.video_writer.write(frame)
                    else:
                        # 如果没有帧可写，并且还没有收到停止信号，则等待一小段时间
                        # 这避免了在线程停止信号到达前，缓冲区恰好为空的情况
                        if not self.thread_stop_event.is_set():
                            time.sleep(0.01) # 短暂休眠，避免忙等待
                
            logging.info(f"视频写入线程停止，文件 {file_path} 已完成。")

        except Exception as e:
            logging.critical(f"视频写入线程发生严重错误: {e}", exc_info=True)
        finally:
            if self.video_writer:
                self.video_writer.release()
                logging.info("视频写入器已释放。")
            self.is_recording = False # 确保状态更新
            self.thread_stop_event.set() # 确保停止事件被设置

    def start_recording(self, filename="output.mp4"):
        """
        开始录制视频，将捕获到的帧写入文件。
        返回录制文件的完整路径，如果无法开始录制则返回 None。
        """
        if self.is_recording:
            logging.warning("已经在录制中，请勿重复开始。")
            return os.path.join(self.output_dir, filename) # 返回当前文件名

        if not self.cap or not self.cap.isOpened():
            logging.error("摄像头未开启或无法访问，无法开始录制。")
            return None

        # 清空缓冲区
        with self.lock:
            self.frames_buffer = []
        
        self.thread_stop_event.clear() # 清除停止事件，准备开始新录制
        self.is_recording = True
        self.recording_thread = threading.Thread(target=self._write_frames_to_video, args=(filename,))
        self.recording_thread.daemon = True # 设置为守护线程，主程序退出时自动终止
        self.recording_thread.start()
        logging.info(f"视频录制已启动到文件: {os.path.join(self.output_dir, filename)}")
        return os.path.join(self.output_dir, filename)

    def stop_recording(self):
        """
        停止视频录制。
        """
        if self.is_recording:
            logging.info("正在停止视频录制...")
            self.thread_stop_event.set() # 通知写入线程停止
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=5) # 等待录制线程完成，最多等待5秒
                if self.recording_thread.is_alive():
                    logging.warning("视频录制线程未能及时停止。可能存在未处理的帧。")
            self.is_recording = False
            logging.info("视频录制已停止。")
        else:
            logging.info("未在录制中，无需停止。")

    def stop_camera(self):
        """
        停止摄像头捕获。
        """
        if self.cap and self.cap.isOpened():
            self.cap.release()
            logging.info("摄像头已停止并释放。")
            self.cap = None # 将cap设置为None，表示摄像头已关闭
        else:
            logging.warning("摄像头未开启，无需停止。")

    def release_resources(self):
        """
        释放所有资源，包括停止录制和关闭摄像头。
        """
        self.stop_recording()
        self.stop_camera()
        logging.info("VideoProcessor 资源已清理。")


# --- 示例使用 (仅用于测试 video_processor.py 自身的功能) -- 杨怡修改
if __name__ == "__main__":
    cam_idx = 0
    processor = VideoProcessor(camera_index=cam_idx, resolution=(640, 480), fps=30) # 调整分辨率和帧率

    video_file_path = None
    try:
        processor.start_camera()
        video_file_path = processor.start_recording(filename="my_interview_test.mp4")

        start_time = time.time()
        duration = 10 # 录制 10 秒

        print(f"开始录制 {duration} 秒视频...")
        while time.time() - start_time < duration:
            frame = processor.capture_frame()
            if frame is not None:
                processor.add_frame_to_buffer(frame)
                # 可选：实时显示帧
                cv2.imshow('Live Camera Test', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            time.sleep(1 / processor.fps) # 根据实际帧率控制循环时间

    except Exception as e:
        logging.error(f"测试过程中发生错误: {e}", exc_info=True)
    finally:
        print("停止录制并释放资源...")
        processor.release_resources()
        cv2.destroyAllWindows()
        print(f"视频已保存到: {video_file_path}")
        print("测试结束。")