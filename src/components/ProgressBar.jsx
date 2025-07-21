import React from 'react';
import { Progress } from 'antd';

export default function ProgressBar({ step, total }) {
  return (
    <Progress percent={Math.round((step / total) * 100)} />
  );
}
