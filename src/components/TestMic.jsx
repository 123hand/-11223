import React, { useEffect } from 'react';

export default function TestMic() {
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        alert('麦克风权限已获取！');
        // 关闭流，防止占用
        stream.getTracks().forEach(track => track.stop());
      })
      .catch(err => {
        alert('麦克风权限被拒绝或出错: ' + err.message);
      });
  }, []);
  return <div></div>;
}