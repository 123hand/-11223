import React from 'react';

export default function FeedbackPanel({ feedback }) {
  return (
    <div style={{ marginTop: 16 }}>
      <b>AI评价：</b>
      <div style={{ minHeight: 32 }}>{feedback}</div>
    </div>
  );
}
