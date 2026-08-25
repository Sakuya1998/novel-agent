import { AlertTriangle, RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  onReset?: () => void;
}

interface State {
  failed: boolean;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    globalThis.reportError?.(new Error("工作台渲染失败", { cause: { error, componentStack: info.componentStack } }));
  }

  private reset = () => {
    this.setState({ failed: false });
    if (this.props.onReset) this.props.onReset();
    else window.location.reload();
  };

  render() {
    if (!this.state.failed) return this.props.children;

    return <main className="fatal-error" role="alert">
      <AlertTriangle size={26} />
      <h1>工作台暂时无法显示</h1>
      <p>界面遇到了意外错误。重新加载不会删除已经保存的作品数据。</p>
      <button type="button" className="primary-button" onClick={this.reset}>
        <RefreshCw size={15} />重新加载工作台
      </button>
    </main>;
  }
}
