import React, { useEffect, useRef } from 'react';
import { getSocket } from '../utils/socket';

export default function AudioRecorder({ canAnswer }) {
  const audioRef = useRef(null);

  useEffect(() => {
    let audioContext, source, processor, stream;
    
    if (canAnswer) {
      console.log('开始录音...');
      navigator.mediaDevices.getUserMedia({ audio: true }).then(s => {
        stream = s;
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        source = audioContext.createMediaStreamSource(stream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioContext.destination);
        processor.onaudioprocess = (e) => {
          const input = e.inputBuffer.getChannelData(0);
          let buf = new Int16Array(input.length);
          for (let i = 0; i < input.length; i++) {
            let s = Math.max(-1, Math.min(1, input[i]));
            buf[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
          }
          // 转换为 bytes 类型发送
          const audioData = new Uint8Array(buf.buffer);
          console.log('【前端音频】发送音频帧，长度:', audioData.length, '字节');
          getSocket().emit('audio_stream', audioData);
        };
      }).catch(err => {
        console.error('麦克风权限被拒绝或出错', err);
      });
    } else {
      console.log('停止录音...');
    }
    
    return () => {
      if (processor) processor.disconnect();
      if (source) source.disconnect();
      if (audioContext) audioContext.close();
      if (stream) stream.getTracks().forEach(track => track.stop());
    };
  }, [canAnswer]);

  return <div style={{height: 0}}></div>;
}
