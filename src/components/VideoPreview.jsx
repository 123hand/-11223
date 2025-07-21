import React, { useRef, useEffect, useState } from 'react';

export default function VideoPreview({ onEmotionResult }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [backendResult, setBackendResult] = useState(null);
  const [detecting, setDetecting] = useState(false);
  const [videoError, setVideoError] = useState(null);
  const intervalRef = useRef(null);
  const streamRef = useRef(null);
  const [emotions, setEmotions] = useState([]); // 新增

  // 自动开启视频检测
  const startVideoDetection = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        video: { 
          width: { ideal: 320 },
          height: { ideal: 240 }
        }, 
        audio: false 
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
      setDetecting(true);
      setVideoError(null);

      // 开始定期发送图片到后端
      intervalRef.current = setInterval(() => {
        if (
          videoRef.current &&
          canvasRef.current &&
          videoRef.current.readyState === 4
        ) {
          const ctx = canvasRef.current.getContext('2d', { willReadFrequently: true });
          ctx.drawImage(videoRef.current, 0, 0, 320, 240);
          const dataUrl = canvasRef.current.toDataURL('image/jpeg');
          fetch('/api/face_emotion', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl })
          })
            .then(res => res.json())
            .then(data => {
              setBackendResult(data);
              if (data && data.emotion) {
                setEmotions(prev => {
                  const newArr = [...prev, data.emotion];
                  if (onEmotionResult) onEmotionResult(newArr); // 通知父组件
                  return newArr;
                });
              }
              console.log('后端返回:', data);
            })
            .catch(err => {
              console.error('后端API调用失败', err);
            });
        }
      }, 2000);

    } catch (err) {
      console.error('无法打开摄像头:', err);
      setVideoError('无法打开摄像头，请检查设备权限');
      setDetecting(false);
    }
  };

  // 停止检测
  const handleStopDetect = () => {
    setDetecting(false);
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  };

  // 组件加载时自动开启视频
  useEffect(() => {
    startVideoDetection();
    
    // 组件卸载时清理
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []); // 空依赖数组，只在组件加载时执行一次

  return (
    <>
      <div style={{ margin: '10px 0' }}>
        {detecting ? (
          <button onClick={handleStopDetect} style={{ 
            backgroundColor: '#ff4d4f', 
            color: 'white', 
            border: 'none', 
            padding: '8px 16px', 
            borderRadius: '4px' 
          }}>
            关闭视频
          </button>
        ) : (
          <button onClick={startVideoDetection} style={{ 
            backgroundColor: '#1890ff', 
            color: 'white', 
            border: 'none', 
            padding: '8px 16px', 
            borderRadius: '4px' 
          }}>
            重新开启视频
          </button>
        )}
      </div>
      
      {videoError && (
        <div style={{ 
          color: '#ff4d4f', 
          marginBottom: 10, 
          padding: 8, 
          backgroundColor: '#fff2f0', 
          borderRadius: 4 
        }}>
          {videoError}
        </div>
      )}
      
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        width={320}
        height={240}
        style={{ 
          marginBottom: 10, 
          display: detecting ? 'block' : 'none',
          border: '2px solid #1890ff',
          borderRadius: '8px'
        }}
      />
      
      {/* canvas 不再渲染到页面，只用于采集图片 */}
      <canvas ref={canvasRef} width={320} height={240} style={{ display: 'none' }} />
      
      {/* 隐藏调试信息，用户不需要看到 emotion 数据 */}
      {/* 
      <div>
        {backendResult && (
          <pre style={{ 
            backgroundColor: '#f6f8fa', 
            padding: 12, 
            borderRadius: 4,
            fontSize: 12 
          }}>
            {JSON.stringify(backendResult, null, 2)}
          </pre>
        )}
      </div>
      */}
    </>
  );
}
