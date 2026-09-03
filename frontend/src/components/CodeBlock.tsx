import { useState } from 'react';
import { runCode } from '../lib/api';

interface Props {
  language: string;
  code: string;
  children: React.ReactNode;
}

export default function CodeBlock({ language, code, children }: Props) {
  const [output, setOutput] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState<number>(0);
  const [running, setRunning] = useState(false);

  const handleRun = async () => {
    setRunning(true);
    setOutput(null);
    setError(null);
    try {
      const result = await runCode(language, code);
      setOutput(result.output);
      setError(result.error);
      setTime(result.execution_time);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Execution failed');
    } finally {
      setRunning(false);
    }
  };

  const isRunnable = ['python', 'javascript'].includes(language);

  return (
    <div className="code-block-wrap">
      <div className="code-block-head">
        <span className="code-block-lang">{language || 'text'}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {isRunnable && (
            <button
              className="code-run-btn"
              onClick={handleRun}
              disabled={running}
            >
              {running ? 'Running...' : '\u25B6 Run'}
            </button>
          )}
        </div>
      </div>
      {children}
      {output !== null && (
        <div className="code-output success">
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{output}</pre>
          <div className="code-output-time">Executed in {time.toFixed(2)}s</div>
        </div>
      )}
      {error && (
        <div className="code-output error">
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{error}</pre>
        </div>
      )}
    </div>
  );
}
