import React, { useState, useEffect } from 'react';

const FIELD_LIST = ['人工智能', '大数据', '物联网', '智能系统'];

export default function ExamPanel() {
  const [field, setField] = useState(FIELD_LIST[0]);
  const [questions, setQuestions] = useState({});
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [answer, setAnswer] = useState('');
  const [review, setReview] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/exam_questions')
      .then(res => res.json())
      .then(data => setQuestions(data.questions || {}));
  }, []);

  useEffect(() => {
    if (questions[field] && questions[field].length > 0) {
      setCurrentQuestion(questions[field][Math.floor(Math.random() * questions[field].length)]);
      setAnswer('');
      setReview('');
    }
  }, [field, questions]);

  const handleChangeQuestion = () => {
    if (questions[field] && questions[field].length > 0) {
      setCurrentQuestion(questions[field][Math.floor(Math.random() * questions[field].length)]);
      setAnswer('');
      setReview('');
    }
  };

  const handleSubmit = async () => {
    if (!answer.trim()) return;
    setLoading(true);
    setReview('');
    const res = await fetch('/api/exam_review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        field,
        question: currentQuestion.question,
        answer
      })
    });
    const data = await res.json();
    setReview(data.review || '批改失败，请稍后重试。');
    setLoading(false);
  };

  return (
    <div style={{ maxWidth: 700, margin: '0 auto' }}>
      <div style={{ fontWeight: 'bold', fontSize: 20, marginBottom: 16 }}>笔试题练习</div>
      <div style={{ marginBottom: 16 }}>
        <span>选择领域：</span>
        <select value={field} onChange={e => setField(e.target.value)} style={{ fontSize: 16, padding: 4 }}>
          {FIELD_LIST.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
        <button onClick={handleChangeQuestion} style={{ marginLeft: 16 }}>换一道题</button>
      </div>
      {currentQuestion && (
        <div style={{ marginBottom: 16, background: '#f9f9f9', padding: 16, borderRadius: 8 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 8 }}>题目：</div>
          <div>{currentQuestion.question}</div>
        </div>
      )}
      <textarea
        value={answer}
        onChange={e => setAnswer(e.target.value)}
        rows={6}
        style={{ width: '100%', fontSize: 16, marginBottom: 16, padding: 8, borderRadius: 4, border: '1px solid #ccc' }}
        placeholder="请输入你的答案..."
      />
      <div>
        <button onClick={handleSubmit} disabled={loading || !answer.trim()} style={{ fontSize: 16, padding: '6px 24px' }}>
          {loading ? '批改中...' : '提交批改'}
        </button>
      </div>
      {review && (
        <div style={{ marginTop: 24, background: '#e3f2fd', padding: 16, borderRadius: 8 }}>
          <div style={{ fontWeight: 'bold', marginBottom: 8 }}>批改结果：</div>
          <div style={{ whiteSpace: 'pre-line' }}>{review}</div>
        </div>
      )}
    </div>
  );
} 