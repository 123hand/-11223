import React, { useState, useEffect, useRef } from 'react';
import { Card, Button, Divider, message } from 'antd';
import { initSocket, closeSocket, getSocket } from '../utils/socket';
import { startInterview, stopInterview } from '../api/interview';
import AudioRecorder from './AudioRecorder';
import VideoPreview from './VideoPreview';
import ReactECharts from 'echarts-for-react';
import ExamPanel from './ExamPanel'; // 新增
import UserProfile from './UserProfile'; // 新增
import ResumeMaker from './ResumeMaker';
import { UserOutlined, FileTextOutlined, EditOutlined, SolutionOutlined } from '@ant-design/icons';

const NAVS = [
  { key: 'interview', label: 'AI面试', icon: <SolutionOutlined /> },
  { key: 'exam', label: '笔试题', icon: <FileTextOutlined /> },
  { key: 'resume', label: '制作简历', icon: <EditOutlined /> },
  { key: 'user', label: '个人中心', icon: <UserOutlined /> },
];

export default function InterviewPanel() {
  const [question, setQuestion] = useState('');
  const [userAnswer, setUserAnswer] = useState('');
  const [canAnswer, setCanAnswer] = useState(false);
  const [isAnswering, setIsAnswering] = useState(false); // 是否正在回答
  const [interviewing, setInterviewing] = useState(false);
  const [forceStopped, setForceStopped] = useState(false);
  const [interviewHistory, setInterviewHistory] = useState([]);
  const [showReportBtn, setShowReportBtn] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportResult, setReportResult] = useState(null);
  const [currentAnswerText, setCurrentAnswerText] = useState(''); // 当前回答的实时文本（不显示）
  const [processedAnswer, setProcessedAnswer] = useState(''); // AI处理后的回答
  const [hasAnswered, setHasAnswered] = useState(false); // 新增：用于判断用户是否已经作答过
  const [videoEmotions, setVideoEmotions] = useState([]);
  const [resumeText, setResumeText] = useState('');
  const socketRef = useRef(null);
  const videoRef = useRef(null); // 新增：数字人视频引用
  const [showInterviewerVideo, setShowInterviewerVideo] = useState(false); // 控制视频显示
  // 1. 面试sid状态，优先从localStorage读取
  const [interviewSid, setInterviewSid] = useState(() => localStorage.getItem('interview_sid') || null);
  
  // 添加防抖机制
  const debounceRef = useRef(null);
  const lastAsrTextRef = useRef('');
  const asrUpdateCountRef = useRef(0); // 统计ASR更新次数
  const [audioAnalysis, setAudioAnalysis] = useState(''); // 新增：语音分析结果
  const [audioAnalysisList, setAudioAnalysisList] = useState([]); // 新增：累计所有轮次语音分析

  // 在主组件内增加笔试题入口和路由切换
  const [activeTab, setActiveTab] = useState('interview'); // 'interview' | 'exam' | 'user'

  useEffect(() => {
    const socket = initSocket();
    socketRef.current = socket;

    socket.on('ai_question', data => {
      setQuestion(data.text);
      setUserAnswer('');
      setCurrentAnswerText(''); // 清空当前回答
      setProcessedAnswer(''); // 清空处理后的回答
      setIsAnswering(false); // 重置回答状态
      setCanAnswer(true); // 允许开始回答
      setHasAnswered(false); // 重置作答标记，允许回答新问题
      // 数字人视频：AI提问时显示并播放，面试结束时隐藏
      if (data.text && data.text.includes('面试已结束')) {
        setShowInterviewerVideo(false);
        if (videoRef.current) videoRef.current.pause();
      } else {
        setShowInterviewerVideo(true);
        setTimeout(() => {
          if (videoRef.current) {
            videoRef.current.currentTime = 0;
            videoRef.current.play();
          }
        }, 100);
      }
    });
    
    socket.on('can_answer', () => {
      setCanAnswer(true);
      setIsAnswering(false); // 关键：允许重新点击“开始回答”
      setCurrentAnswerText('');
      setProcessedAnswer('');
      message.info('请点击"开始回答"按钮开始作答');
      // 数字人视频：用户作答时隐藏并暂停
      setShowInterviewerVideo(false);
      if (videoRef.current) {
        videoRef.current.pause();
      }
    });
    
    socket.on('asr_result', data => {
      if (isAnswering) {
        // 防抖处理ASR结果
        if (data.text && data.text.trim()) {
          const newText = data.text.trim();
          asrUpdateCountRef.current += 1;
          
          // 清除之前的防抖定时器
          if (debounceRef.current) {
            clearTimeout(debounceRef.current);
          }
          
          // 设置新的防抖定时器
          debounceRef.current = setTimeout(() => {
            setCurrentAnswerText(prevText => {
              // 如果内容相同，不更新
              if (prevText === newText) {
                return prevText;
              }
              
              // 如果新内容包含之前的内容，说明是扩展，直接使用
              if (prevText && newText.includes(prevText)) {
                return newText;
              }
              
              // 如果之前内容包含新内容，说明是重复，保持原内容
              if (prevText && prevText.includes(newText)) {
                return prevText;
              }
              
              // 如果内容完全不同，可能是新分段，累加内容
              if (prevText && !newText.includes(prevText) && !prevText.includes(newText)) {
                return prevText + ' ' + newText;
              }
              
              // 其他情况直接使用新内容
              return newText;
            });
            console.log(`ASR中间结果（防抖后，第${asrUpdateCountRef.current}次更新）:`, newText);
          }, 150); // 增加防抖延迟到150ms，减少更新频率
        }
      }
      if (data.is_final) {
        console.log('语音识别完成:', data.text);
        asrUpdateCountRef.current = 0; // 重置计数器
      }
    });
    
    socket.on('ai_feedback', data => {
      // 如果有处理后的回答，显示它
      if (data.processed_answer) {
        setProcessedAnswer(data.processed_answer);
        setUserAnswer(data.processed_answer);
      }
      setCanAnswer(false);
      setIsAnswering(false); // 结束回答状态
      setHasAnswered(true); // 标记用户已经作答过
      // 保存本轮问答到历史（只保留AI提问和AI整理后的用户回答）
      setInterviewHistory(prev => [
        ...prev,
        {
          question,
          answer: data.processed_answer || userAnswer
        }
      ]);
    });

    return () => {
      closeSocket();
    };
  }, [question, userAnswer, isAnswering]);

  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;
    socket.on('interview_force_stop', () => {
      setForceStopped(true);
      setInterviewing(false);
      setQuestion('');
      setUserAnswer('');
      setIsAnswering(false);
      setCanAnswer(false);
      setCurrentAnswerText('');
      setProcessedAnswer('');
      setShowReportBtn(true);
      setShowInterviewerVideo(false); // 新增：面试结束时隐藏虚拟人
      if (videoRef.current) {
        videoRef.current.pause();
      }
    });
    return () => {
      socket.off('interview_force_stop');
    };
  }, []);

  // 监听后端返回的语音分析结果（假设后端通过answer_result或ai_feedback事件返回audio_analysis字段）
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket) return;
    socket.on('answer_result', data => {
      if (data.audio_analysis) {
        console.log('【调试】收到后端语音分析:', data.audio_analysis);
        setAudioAnalysisList(prev => {
          const newList = [...prev, data.audio_analysis];
          console.log('【调试】累计语音分析列表:', newList);
          return newList;
        });
      }
    });
    // 兼容ai_feedback事件
    socket.on('ai_feedback', data => {
      if (data.audio_analysis) {
        console.log('【调试】收到后端语音分析(ai_feedback):', data.audio_analysis);
        setAudioAnalysisList(prev => {
          const newList = [...prev, data.audio_analysis];
          console.log('【调试】累计语音分析列表:', newList);
          return newList;
        });
      }
    });
    return () => {
      socket.off('answer_result');
      socket.off('ai_feedback');
    };
  }, []);

  useEffect(() => {
    console.log('【调试】audioAnalysisList变化:', audioAnalysisList);
  }, [audioAnalysisList]);

  const handleStart = async () => {
    setForceStopped(false);
    setShowReportBtn(false);
    setReportResult(null);
    setInterviewHistory([]);
    setIsAnswering(false);
    setCurrentAnswerText('');
    setProcessedAnswer('');
    setHasAnswered(false); // 重置作答标记
    setShowInterviewerVideo(true); // 新增：点击开始面试时立刻显示虚拟人
    setAudioAnalysisList([]); // 新增：开始面试时清空语音分析累计
    setTimeout(() => {
      if (videoRef.current) {
        videoRef.current.currentTime = 0;
        videoRef.current.play();
      }
    }, 100);
    const socket = getSocket();
    if (socket) {
      setInterviewSid(socket.id);
      localStorage.setItem('interview_sid', socket.id); // 保存到localStorage
    }
    await startInterview();
    setInterviewing(true);
  };

  const handleStop = async () => {
    if (forceStopped) return;
    await stopInterview();
    const socket = getSocket();
    if (socket) socket.emit('interview_end');
    setInterviewing(false);
    setForceStopped(true);
    setQuestion('');
    setUserAnswer('');
    setIsAnswering(false);
    setCanAnswer(false);
    setCurrentAnswerText('');
    setProcessedAnswer('');
    setShowReportBtn(true);
    // 不要清空 interviewHistory 和 reportResult，这样才能生成报告
  };

  // 开始回答
  const handleStartAnswer = () => {
    setIsAnswering(true);
    setCurrentAnswerText(''); // 清空之前的回答
    setUserAnswer(''); // 清空最终回答
    setProcessedAnswer(''); // 清空处理后的回答
    message.info('开始回答，请说话或输入文字');
  };

  // 结束回答
  const handleEndAnswer = () => {
    setIsAnswering(false);
    const finalAnswer = currentAnswerText;
    console.log('结束回答，最终答案:', finalAnswer);
    setUserAnswer(finalAnswer);
    setCurrentAnswerText('');
    setCanAnswer(false);

    const socket = getSocket();
    if (socket) {
      // 先发送end_answer事件，确保后端分析语音
      socket.emit('end_answer');
      // 再发送user_answer事件
      if (finalAnswer && finalAnswer.trim()) {
        console.log('发送回答给后端:', finalAnswer);
        socket.emit('user_answer', { text: finalAnswer });
        message.info('回答已提交，等待AI反馈');
      } else {
        console.log('回答内容为空或无效:', finalAnswer);
        message.warning('没有检测到回答内容');
        // 允许重新作答
        setCanAnswer(true);
        setIsAnswering(false);
      }
    }
  };

  // 统计情绪分布，生成更有信息量的 video_analysis
  function summarizeEmotions(emotions) {
    if (!emotions || emotions.length === 0) return '无视频数据';
    const stat = {};
    emotions.forEach(e => { stat[e] = (stat[e] || 0) + 1; });
    const total = emotions.length;
    return Object.entries(stat)
      .map(([emo, count]) => `${emo}：${count}次`)
      .join('，') + `。总采集帧数：${total}`;
  }

  // 生成评测报告
  const handleGenerateReport = async () => {
    setReportLoading(true);
    setReportResult(null);
    // 拉取所有轮次语音分析
    let audioAnalysisText = '';
    try {
      const audioRes = await fetch('/api/get_audio_analysis');
      const audioData = await audioRes.json();
      audioAnalysisText = (audioData.audio_analysis || []).map((txt, idx) => `第${idx+1}轮：${txt}`).join('\n');
    } catch (e) {
      audioAnalysisText = '无语音分析数据';
    }
    // 统计情绪分布
    const videoSummary = summarizeEmotions(videoEmotions);
    try {
      const res = await fetch('/api/interview/result', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          history: interviewHistory,
          video_analysis: videoSummary,
          resume_text: resumeText,
          audio_analysis: audioAnalysisText,
        }),
      });
      const data = await res.json();
      setReportResult(data);
      setShowReportBtn(false);
    } catch (e) {
      setReportResult({ error: '生成评测报告失败' });
    }
    setReportLoading(false);
  };

  function getRadarOption(scores) {
    const indicators = [
      { name: '专业知识水平', max: 100 },
      { name: '技能匹配度', max: 100 },
      { name: '语言表达能力', max: 100 },
      { name: '逻辑思维能力', max: 100 },
      { name: '创新能力', max: 100 },
      { name: '应变抗压能力', max: 100 }
    ];
    return {
      tooltip: {},
      radar: {
        indicator: indicators,
        radius: 90
      },
      series: [{
        type: 'radar',
        data: [
          {
            value: [
              scores['专业知识水平'] || 0,
              scores['技能匹配度'] || 0,
              scores['语言表达能力'] || 0,
              scores['逻辑思维能力'] || 0,
              scores['创新能力'] || 0,
              scores['应变抗压能力'] || 0
            ],
            name: '面试评测'
          }
        ]
      }]
    };
  }

  function renderReportResult(reportResult) {
    if (!reportResult) return null;
    const { scores, radar, key_issues, suggestions, summary, multimodal_analysis } = reportResult;
    return (
      <div style={{ lineHeight: 2, fontSize: 16 }}>
        <b>六大维度评分：</b>
        <ul>
          {scores && Object.entries(scores).map(([k, v]) => (
            <li key={k}>{k}：<b>{v}</b> 分</li>
          ))}
        </ul>
        <b>主要问题：</b>
        <ul>
          {key_issues && key_issues.map((item, idx) => (
            <li key={idx}><b>{item.question}：</b>{item.issue}</li>
          ))}
        </ul>
        <b>多模态分析：</b>
        <ul>
          {multimodal_analysis && Object.entries(multimodal_analysis).map(([k, v]) => (
            <li key={k}>{k}：{v}</li>
          ))}
        </ul>
        <b>改进建议：</b>
        <ul>
          {suggestions && suggestions.map((s, idx) => (
            <li key={idx}>{s}</li>
          ))}
        </ul>
        <b>总结：</b>
        <div style={{ marginTop: 8 }}>{summary}</div>
      </div>
    );
  }

  // 彻底清理中间栏，只保留主导航栏和内容区
  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'linear-gradient(120deg, #eaf6ff 0%, #f6f8fb 100%)' }}>
      {/* 美化后的AI面试系统导航栏 */}
      <div style={{
        width: 240,
        background: 'linear-gradient(180deg, #aee2ff 0%, #4f8cff 100%)',
        color: '#fff',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 48,
        borderTopRightRadius: 36,
        borderBottomRightRadius: 36,
        boxShadow: '4px 0 32px #b3d8ff33',
        minHeight: '100vh',
      }}>
        <div style={{ fontWeight: 'bold', fontSize: 30, marginBottom: 60, letterSpacing: 2, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span role="img" aria-label="logo" style={{ fontSize: 38 }}>💻</span>智能面试系统
        </div>
        <div style={{ width: '100%' }}>
          {NAVS.map(nav => (
            <div
              key={nav.key}
              style={{
                marginBottom: 26,
                cursor: 'pointer',
                background: activeTab === nav.key ? 'linear-gradient(90deg, #fff 60%, #e3f2fd 100%)' : 'transparent',
                color: activeTab === nav.key ? '#1976d2' : '#fff',
                borderRadius: 18,
                padding: '16px 0',
                textAlign: 'center',
                fontWeight: 600,
                fontSize: 20,
                boxShadow: activeTab === nav.key ? '0 4px 16px #b3d8ff44' : 'none',
                transition: 'all 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 14,
                position: 'relative',
                border: activeTab === nav.key ? '2.5px solid #1976d2' : '2.5px solid transparent',
              }}
              onClick={() => setActiveTab(nav.key)}
              onMouseEnter={e => e.currentTarget.style.background = activeTab === nav.key ? 'linear-gradient(90deg, #fff 60%, #e3f2fd 100%)' : 'linear-gradient(90deg, #e3f2fd 0%, #b3e5fc 100%)'}
              onMouseLeave={e => e.currentTarget.style.background = activeTab === nav.key ? 'linear-gradient(90deg, #fff 60%, #e3f2fd 100%)' : 'transparent'}
            >
              {nav.icon}
              {nav.label}
            </div>
          ))}
        </div>
      </div>
      {/* 右侧内容区，风格和结构保持不变 */}
      <div style={{ flex: 1, padding: '64px 0 64px 0', background: 'linear-gradient(120deg, #fafdff 0%, #eaf6ff 100%)', minHeight: '100vh' }}>
        <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 0 56px 0', borderRadius: 32, boxShadow: '0 8px 48px #b3d8ff22', background: '#fff' }}>
          {activeTab === 'resume' && <ResumeMaker />}
          {activeTab === 'interview' && (
            <Card bordered={false} style={{ marginBottom: 36, borderRadius: 22, boxShadow: '0 6px 32px #b3d8ff33', padding: '32px 0 40px 0', background: 'rgba(255,255,255,0.98)' }}>
              <div style={{ fontSize: 26, fontWeight: 700, color: '#3578e5', marginBottom: 18, letterSpacing: 1 }}>AI模拟面试</div>
              <Divider style={{ margin: '18px 0 28px 0' }} />
              {/* 数字人视频+摄像头人脸识别区 横向并排 */}
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 48, margin: '0 0 36px 0' }}>
                {/* 左：数字人视频 */}
                <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-end' }}>
                  {showInterviewerVideo && (
                    <video
                      ref={videoRef}
                      src="/static/video/interviewer.mp4"
                      loop
                      muted
                      style={{
                        width: 200,
                        height: 290,
                        borderRadius: 20,
                        boxShadow: '0 8px 32px #b6c6e6',
                        objectFit: 'cover',
                        background: 'transparent',
                        zIndex: 10,
                        display: showInterviewerVideo ? 'block' : 'none',
                      }}
                      autoPlay
                    />
                  )}
                </div>
                {/* 右：摄像头人脸识别 */}
                <div style={{ flex: 1, display: 'flex', justifyContent: 'flex-start' }}>
                  <VideoPreview onEmotionResult={setVideoEmotions} />
                </div>
              </div>
              <Card size="small" style={{ marginBottom: 28, borderRadius: 14, background: '#f6faff', border: 'none', padding: '18px 0 18px 0' }}>
                <b style={{ color: '#222', fontSize: 18 }}>AI提问：</b>
                <span style={{ fontSize: 18, color: '#333', marginLeft: 12 }}>{question}</span>
              </Card>
              <Card style={{ marginBottom: 28, borderRadius: 14, padding: 18 }}>
                <b style={{ fontSize: 16 }}>简历信息（可选）：</b>
                <textarea
                  value={resumeText}
                  onChange={e => setResumeText(e.target.value)}
                  rows={6}
                  style={{ width: '100%', marginTop: 10, borderRadius: 8, border: '1px solid #dbeafe', fontSize: 16, padding: 10, background: '#fafdff' }}
                  placeholder="请粘贴或填写你的简历内容，AI将参考简历给出更精准的评测建议"
                />
              </Card>
              <Card size="small" style={{ marginBottom: 28, borderRadius: 14, background: '#f8f8ff', border: 'none', padding: 18 }}>
                <b style={{ color: '#222', fontSize: 16 }}>用户作答：</b>
                <AudioRecorder canAnswer={isAnswering} />
                <div style={{ 
                  minHeight: 32, 
                  background: isAnswering ? '#fffbe6' : '#f5f5f5', 
                  padding: 12, 
                  borderRadius: 8, 
                  fontSize: 17, 
                  marginTop: 10, 
                  transition: 'background 0.3s',
                  border: isAnswering ? '2px solid #faad14' : '1px solid #d9d9d9',
                  position: 'relative',
                }}>
                  {isAnswering
                    ? '正在识别语音，请稍候...'
                    : (hasAnswered
                        ? (processedAnswer || '等待AI整理...')
                        : '')}
                  {isAnswering && (
                    <div style={{ 
                      position: 'absolute', 
                      top: -8, 
                      right: 8, 
                      background: '#52c41a', 
                      color: 'white', 
                      padding: '2px 8px', 
                      borderRadius: 10, 
                      fontSize: 13 
                    }}>
                      识别中
                    </div>
                  )}
                </div>
                {canAnswer && !isAnswering && !hasAnswered && (
                  <Button 
                    type="primary" 
                    onClick={handleStartAnswer}
                    style={{ marginTop: 14, marginRight: 12, fontSize: 17, borderRadius: 8, height: 44, width: 120 }}
                  >
                    开始回答
                  </Button>
                )}
                {isAnswering && (
                  <Button 
                    danger 
                    onClick={handleEndAnswer}
                    style={{ marginTop: 14, fontSize: 17, borderRadius: 8, height: 44, width: 120 }}
                  >
                    结束回答
                  </Button>
                )}
              </Card>
              {interviewHistory.length > 0 && (
                <Card size="small" style={{ marginBottom: 28, borderRadius: 14, background: '#f6faff', border: 'none', padding: 18 }}>
                  <b style={{ color: '#222', fontSize: 16 }}>历史问答：</b>
                  <div style={{ marginTop: 10 }}>
                    {interviewHistory.map((item, idx) => (
                      <div key={idx} style={{ marginBottom: 12, fontSize: 15 }}>
                        <div><b>AI提问：</b>{item.question}</div>
                        <div><b>AI整理后的用户回答：</b>{item.answer}</div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              <div style={{ textAlign: 'center', marginTop: 36 }}>
                <Button type="primary" size="large" onClick={handleStart} disabled={interviewing} style={{ width: 160, borderRadius: 10, marginRight: 24, fontSize: 18, height: 48 }}>开始面试</Button>
                <Button danger size="large" onClick={handleStop} disabled={!interviewing} style={{ width: 160, borderRadius: 10, fontSize: 18, height: 48 }}>结束面试</Button>
              </div>
            </Card>
          )}
          {showReportBtn && (
            <div style={{ marginTop: 40, textAlign: 'center' }}>
              <Button type="primary" loading={reportLoading} onClick={handleGenerateReport} style={{ fontSize: 18, borderRadius: 10, height: 48, width: 240 }}>
                {reportLoading ? '生成中...' : '生成多维度评测报告'}
              </Button>
            </div>
          )}
          {reportResult && reportResult.scores && (
            <div style={{ margin: '36px 0' }}>
              <ReactECharts option={getRadarOption(reportResult.scores)} style={{ height: 400 }} />
            </div>
          )}
          {reportResult && (
            <Card style={{ marginTop: 36, borderRadius: 18, background: '#f8faff', boxShadow: '0 2px 12px #e0e7ff' }}>
              <h3 style={{ fontSize: 20, color: '#3578e5', marginBottom: 18 }}>多维度评测报告</h3>
              {renderReportResult(reportResult)}
            </Card>
          )}
          {activeTab === 'exam' && <ExamPanel />}
          {activeTab === 'user' && <UserProfile />}
        </div>
      </div>
    </div>
  );
}
