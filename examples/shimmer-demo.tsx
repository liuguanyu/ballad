/**
 * 流光效果演示（临时 demo，不属主程序）。
 *
 * 真终端里循环渲染 <ShimmerText spinner> 模拟「模型思考中」，看光束扫过 + spinner 旋转。
 * 运行：bun run examples/shimmer-demo.tsx   （Ctrl+C 退出）
 */
import React, { useState, useEffect } from 'react';
import { render, Box, Text, useApp, useInput } from 'ink';
import { ShimmerText } from '../src/platforms/tui/components/ShimmerText.tsx';

function Demo(): React.ReactElement {
  const { exit } = useApp();
  const [thinking, setThinking] = useState(true);

  // 空格切换「思考中 / 结束定格」，Ctrl+C 或 q 退出
  useInput((input, key) => {
    if (input === ' ') {
      setThinking((v) => !v);
    }
    if (input === 'q' || (key.ctrl && input === 'c')) {
      exit();
    }
  });

  // 3 秒后自动演示「思考结束→静止」，再 2 秒恢复，循环
  useEffect(() => {
    const t = setInterval(() => setThinking((v) => !v), 3500);
    return () => clearInterval(t);
  }, []);

  return (
    <Box flexDirection="column" padding={1}>
      <Text color="gray">流光效果演示 · 空格切换思考/静止 · q 退出</Text>
      <Text> </Text>

      <Box>
        <Text color="gray">思考态(spinner+流光)：</Text>
      </Box>
      <ShimmerText text="Thinking… 正在推理你的需求" spinner active={thinking} />
      <Text> </Text>

      <Box>
        <Text color="gray">纯流光(无 spinner)：</Text>
      </Box>
      <ShimmerText text="ballad — a brain/mouth split coding agent" active={thinking} />
      <Text> </Text>

      <Box>
        <Text color="gray">歌词式(自定义暖色)：</Text>
      </Box>
      <ShimmerText
        text="♪ 让流光扫过每一个字符 ♪"
        active={thinking}
        palette={['#8B4513', '#CD853F', '#DAA520', '#FFD700', '#FFF8DC', '#FFD700', '#DAA520', '#CD853F', '#8B4513']}
      />
      <Text> </Text>

      <Text color={thinking ? 'green' : 'yellow'}>
        {thinking ? '● 动画进行中' : '○ 已静止（思考结束）'}
      </Text>
    </Box>
  );
}

render(React.createElement(Demo));
