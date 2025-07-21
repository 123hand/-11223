export function getAudioStream(audioRef, onPCM) {
  navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    source.connect(processor);
    processor.connect(audioContext.destination);
    processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      const pcm = float32ToInt16(inputData);
      if (pcm && pcm.length > 0) onPCM(pcm.buffer);
    };
    audioRef.current = { stream, audioContext, source, processor };
  });
}
export function stopAudioStream(audioRef) {
  const obj = audioRef.current;
  if (!obj) return;
  obj.processor && obj.processor.disconnect();
  obj.source && obj.source.disconnect();
  obj.audioContext && obj.audioContext.close();
  obj.stream && obj.stream.getTracks().forEach(track => track.stop());
  audioRef.current = null;
}
function float32ToInt16(buffer) {
  let l = buffer.length;
  let buf = new Int16Array(l);
  for (let i = 0; i < l; i++) {
    let s = Math.max(-1, Math.min(1, buffer[i]));
    buf[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return buf;
}
