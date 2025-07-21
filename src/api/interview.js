// 面试相关API
export const startInterview = async () => {
  try {
    const response = await fetch('/api/interview/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    return await response.json();
  } catch (error) {
    console.error('开始面试失败:', error);
    throw error;
  }
};

export const stopInterview = async () => {
  try {
    const response = await fetch('/api/interview/stop', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    return await response.json();
  } catch (error) {
    console.error('结束面试失败:', error);
    throw error;
  }
};
