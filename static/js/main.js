// 配置区：请根据实际后端地址调整
const API_START = '/api/interview/start'; // 开始面试API
const API_NEXT = '/api/interview/next';   // 下一题API
const API_STOP = '/api/interview/stop';   // 结束面试API

// Socket.IO连接
const socket = io('ws://localhost:5000'); // 连接SocketIO服务

// DOM元素
const startBtn = document.getElementById('start-btn');
const nextBtn = document.getElementById('next-btn');
const stopBtn = document.getElementById('stop-btn');
const aiQuestionText = document.getElementById('ai-question-text');
const userAnswerText = document.getElementById('user-answer-text');
const aiFeedbackText = document.getElementById('ai-feedback-text');

const videoPreview = document.getElementById('video-preview');
const startRecordBtn = document.getElementById('start-record-btn');
const stopRecordBtn = document.getElementById('stop-record-btn');
const downloadLink = document.getElementById('download-link');

// 状态变量
let mediaRecorder = null;
let recordedChunks = [];
let audioStream = null;
let isInterviewRunning = false;
let audioContext = null;
let processor = null;
let source = null;

// ========== 面试流程相关 ==========

startBtn.onclick = async () => {
    startBtn.disabled = true;
    nextBtn.disabled = false;
    stopBtn.disabled = false;
    aiFeedbackText.textContent = '等待AI评价...';
    userAnswerText.textContent = '等待识别...';
    isInterviewRunning = true;
    await startInterview();
};

nextBtn.onclick = async () => {
    nextBtn.disabled = true;
    userAnswerText.textContent = '等待识别...';
    aiFeedbackText.textContent = '等待AI评价...';
    await nextQuestion();
};

stopBtn.onclick = async () => {
    stopBtn.disabled = true;
    nextBtn.disabled = true;
    isInterviewRunning = false;
    await stopInterview();
    stopASR();
};

async function startInterview() {
    // 向后端请求第一题
    const res = await fetch(API_START, {method: 'POST'});
    const data = await res.json();
    aiQuestionText.textContent = data.question || 'AI未返回问题';
    // 启动流式ASR
    startASR();
}

async function nextQuestion() {
    // 通知后端进入下一题
    const res = await fetch(API_NEXT, {method: 'POST'});
    const data = await res.json();
    aiQuestionText.textContent = data.question || 'AI未返回问题';
    // 重新启动ASR
    startASR();
}

async function stopInterview() {
    await fetch(API_STOP, {method: 'POST'});
    aiQuestionText.textContent = '面试已结束';
    userAnswerText.textContent = '';
    aiFeedbackText.textContent = '';
}

// ========== 流式ASR相关 ==========
function startASR() {
    userAnswerText.textContent = '正在识别...';
    stopASR();
    navigator.mediaDevices.getUserMedia({audio: true}).then(stream => {
        audioStream = stream;
        // 强制采样率为16000
        audioContext = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 16000});
        console.log('AudioContext采样率:', audioContext.sampleRate);
        source = audioContext.createMediaStreamSource(audioStream);
        // bufferSize用4096，单声道
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioContext.destination);
        let lastSend = Date.now();
        processor.onaudioprocess = (e) => {
            if (Date.now() - lastSend < 256) return; // 256ms节流
            lastSend = Date.now();
            const inputData = e.inputBuffer.getChannelData(0);
            if (!inputData || inputData.length === 0) return; // 防止空数据
            const pcm = float32ToInt16(inputData);
            if (pcm && pcm.length > 0) {
                console.log('推送音频帧，长度:', pcm.length * 2, '采样点:', pcm.length);
                socket.emit('audio_stream', pcm.buffer); // 发送ArrayBuffer
            }
        };
    });
}

function stopASR() {
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    if (source) {
        source.disconnect();
        source = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (audioStream) {
        audioStream.getTracks().forEach(track => track.stop());
        audioStream = null;
    }
}

// 监听后端ASR识别结果
document.addEventListener('DOMContentLoaded', () => {
    socket.on('asr_result', (data) => {
        if (data.text) userAnswerText.textContent = data.text;
        if (data.is_final) {
            aiFeedbackText.textContent = data.feedback || '无AI评价';
            nextBtn.disabled = false;
            stopASR();
            // 恢复高亮样式
            userAnswerText.style.background = '';
            userAnswerText.style.color = '';
        }
    });
    socket.on('ai_question', (data) => {
        if (data && data.text) {
            aiQuestionText.textContent = data.text;
        }
    });
    socket.on('ai_feedback', (data) => {
        if (data && data.text) {
            aiFeedbackText.textContent = data.text;
        }
    });
    // 优化：高亮提示在ASR监听期间一直存在
    socket.on('can_answer', () => {
        userAnswerText.textContent = '请开始回答...';
        userAnswerText.style.background = '#fffbe6';
        userAnswerText.style.color = '#d48806';
    });
});

function float32ToInt16(buffer) {
    let l = buffer.length;
    let buf = new Int16Array(l);
    for (let i = 0; i < l; i++) {
        let s = Math.max(-1, Math.min(1, buffer[i]));
        buf[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return buf;
}

// ========== 录像相关 ==========
let videoStream = null;

startRecordBtn.onclick = async () => {
    startRecordBtn.disabled = true;
    stopRecordBtn.disabled = false;
    downloadLink.style.display = 'none';
    videoStream = await navigator.mediaDevices.getUserMedia({video: true, audio: false});
    videoPreview.srcObject = videoStream;
    mediaRecorder = new MediaRecorder(videoStream, {mimeType: 'video/webm'});
    recordedChunks = [];
    mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
        const blob = new Blob(recordedChunks, {type: 'video/webm'});
        downloadLink.href = URL.createObjectURL(blob);
        downloadLink.style.display = 'inline-block';
    };
    mediaRecorder.start();
};

stopRecordBtn.onclick = () => {
    startRecordBtn.disabled = false;
    stopRecordBtn.disabled = true;
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
        videoPreview.srcObject = null;
    }
};
