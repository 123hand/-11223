import React, { useState } from 'react';
import { Card, Input, Button, message, Form, Divider } from 'antd';

export default function ResumeMaker() {
  const [form, setForm] = useState({
    name: '',
    school: '',
    major: '',
    skills: '',
    project: '',
    selfIntro: ''
  });
  const [loading, setLoading] = useState(false);
  const [resume, setResume] = useState('');

  const handleChange = e => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async () => {
    setLoading(true);
    setResume('');
    try {
      const res = await fetch('/api/generate_resume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      });
      const data = await res.json();
      setResume(data.resume || '');
      if (!data.resume) message.error('生成失败');
    } catch (e) {
      message.error('请求失败');
    }
    setLoading(false);
  };

  return (
    <Card title={<span style={{fontSize:20, fontWeight:600, color:'#4f8cff'}}>AI简历生成器</span>} bordered={false} style={{ maxWidth: 520, margin: '0 auto', boxShadow: '0 2px 16px #e0e7ff' }}>
      <Form layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item label="姓名">
          <Input name="name" placeholder="请输入姓名" value={form.name} onChange={handleChange} />
        </Form.Item>
        <Form.Item label="学校">
          <Input name="school" placeholder="请输入学校" value={form.school} onChange={handleChange} />
        </Form.Item>
        <Form.Item label="专业">
          <Input name="major" placeholder="请输入专业" value={form.major} onChange={handleChange} />
        </Form.Item>
        <Form.Item label="技能（用逗号分隔）">
          <Input name="skills" placeholder="如：Python, 数据分析, 英语" value={form.skills} onChange={handleChange} />
        </Form.Item>
        <Form.Item label="项目经历（可选）">
          <Input name="project" placeholder="如：XX系统开发，XX比赛获奖" value={form.project} onChange={handleChange} />
        </Form.Item>
        <Form.Item label="自我评价（可选）">
          <Input name="selfIntro" placeholder="如：学习能力强，沟通良好" value={form.selfIntro} onChange={handleChange} />
        </Form.Item>
        <div style={{textAlign:'center', margin:'24px 0'}}>
          <Button type="primary" size="large" onClick={handleSubmit} loading={loading} style={{width:180, borderRadius:8}}>生成简历</Button>
        </div>
      </Form>
      {resume && (
        <>
          <Divider>AI生成的简历</Divider>
          <div style={{ whiteSpace: 'pre-wrap', background: '#f6faff', padding: 18, borderRadius: 8, fontSize: 16, color: '#222', boxShadow: '0 1px 8px #e0e7ff' }}>
            {resume}
          </div>
        </>
      )}
    </Card>
  );
} 