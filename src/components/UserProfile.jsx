import React, { useState, useEffect } from 'react';

export default function UserProfile() {
  const [info, setInfo] = useState({ nickname: '', avatar_url: '', email: '', phone: '' });
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState({ ...info });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch('/api/user_info')
      .then(res => res.json())
      .then(data => {
        setInfo(data);
        setForm(data);
      });
  }, []);

  const handleChange = e => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSave = async () => {
    setSaving(true);
    const res = await fetch('/api/user_info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form)
    });
    const data = await res.json();
    setInfo(data.user_info || form);
    setEdit(false);
    setSaving(false);
  };

  return (
    <div style={{ maxWidth: 500, margin: '0 auto' }}>
      <div style={{ fontWeight: 'bold', fontSize: 20, marginBottom: 24 }}>个人中心</div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
        <img
          src={info.avatar_url || 'https://cdn.jsdelivr.net/gh/baimingxuan/media-host@master/avatar/default-user.png'}
          alt="avatar"
          style={{ width: 80, height: 80, borderRadius: '50%', marginRight: 24, border: '1px solid #eee', objectFit: 'cover' }}
        />
        <div>
          <div style={{ fontSize: 18, fontWeight: 'bold' }}>{info.nickname || '未命名用户'}</div>
          <div style={{ color: '#888', fontSize: 14 }}>{info.email || '未填写邮箱'}</div>
        </div>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label>昵称：</label>
        {edit ? (
          <input name="nickname" value={form.nickname} onChange={handleChange} style={{ fontSize: 16, padding: 4, width: 200 }} />
        ) : (
          <span style={{ marginLeft: 8 }}>{info.nickname || '未命名用户'}</span>
        )}
      </div>
      <div style={{ marginBottom: 16 }}>
        <label>头像链接：</label>
        {edit ? (
          <input name="avatar_url" value={form.avatar_url} onChange={handleChange} style={{ fontSize: 16, padding: 4, width: 300 }} />
        ) : (
          <span style={{ marginLeft: 8 }}>{info.avatar_url || '未填写'}</span>
        )}
      </div>
      <div style={{ marginBottom: 16 }}>
        <label>邮箱：</label>
        {edit ? (
          <input name="email" value={form.email} onChange={handleChange} style={{ fontSize: 16, padding: 4, width: 240 }} />
        ) : (
          <span style={{ marginLeft: 8 }}>{info.email || '未填写'}</span>
        )}
      </div>
      <div style={{ marginBottom: 16 }}>
        <label>电话：</label>
        {edit ? (
          <input name="phone" value={form.phone} onChange={handleChange} style={{ fontSize: 16, padding: 4, width: 180 }} />
        ) : (
          <span style={{ marginLeft: 8 }}>{info.phone || '未填写'}</span>
        )}
      </div>
      <div>
        {edit ? (
          <>
            <button onClick={handleSave} disabled={saving} style={{ fontSize: 16, padding: '6px 24px', marginRight: 16 }}>{saving ? '保存中...' : '保存'}</button>
            <button onClick={() => setEdit(false)} style={{ fontSize: 16, padding: '6px 24px' }}>取消</button>
          </>
        ) : (
          <button onClick={() => setEdit(true)} style={{ fontSize: 16, padding: '6px 24px' }}>编辑</button>
        )}
      </div>
    </div>
  );
} 