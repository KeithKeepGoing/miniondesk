import * as vscode from 'vscode';

let outputChannel: vscode.OutputChannel | undefined;

function escapeCodeFences(code: string): string {
    return code.replace(/`{3,}/g, (m) => m.split('').join('\u200B'));
}

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('MinionDesk');
    context.subscriptions.push(outputChannel);
    outputChannel.appendLine('MinionDesk Copilot activated 🍌');

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('miniondesk.askStuart', () => askMinion()),
        vscode.commands.registerCommand('miniondesk.reviewCode', () => reviewCode()),
        vscode.commands.registerCommand('miniondesk.explainCode', () => explainCode()),
        vscode.commands.registerCommand('miniondesk.generateTests', () => generateTests()),
        vscode.commands.registerCommand('miniondesk.analyzeLog', () => analyzeLog()),
        vscode.commands.registerCommand('miniondesk.translateScript', () => translateScript()),
    );

    // Status bar item
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(robot) MinionDesk';
    statusBar.tooltip = 'MinionDesk IT Copilot';
    statusBar.command = 'miniondesk.askStuart';
    statusBar.show();
    context.subscriptions.push(statusBar);
}

function getConfig() {
    const cfg = vscode.workspace.getConfiguration('miniondesk');
    return {
        serverUrl: cfg.get<string>('serverUrl', 'http://localhost:8082'),
        defaultMinion: cfg.get<string>('defaultMinion', 'stuart'),
    };
}

function getSelectedText(): string {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { return ''; }
    const selection = editor.selection;
    if (selection.isEmpty) {
        const fullText = editor.document.getText().substring(0, 8000);
        if (fullText.trim()) {
            vscode.window.showWarningMessage('未選取程式碼 — 將使用整個檔案內容（截取至 8000 字元）');
        }
        return fullText;
    }
    return editor.document.getText(selection);
}

function getFileLanguage(): string {
    const editor = vscode.window.activeTextEditor;
    return editor?.document.languageId || 'text';
}

async function sendToMinionDesk(prompt: string, minion?: string): Promise<void> {
    const { serverUrl, defaultMinion } = getConfig();
    const targetMinion = minion || defaultMinion;

    if (!outputChannel) {
        vscode.window.showErrorMessage('MinionDesk: 尚未初始化，請重新載入視窗');
        return;
    }

    let parsedUrl: URL;
    try {
        parsedUrl = new URL(serverUrl);
    } catch (e) {
        vscode.window.showErrorMessage(`MinionDesk: Portal URL 格式無效 — ${serverUrl}`);
        return;
    }
    if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        vscode.window.showErrorMessage('MinionDesk: Portal URL 必須以 http:// 或 https:// 開頭');
        return;
    }
    if (!parsedUrl.hostname) {
        vscode.window.showErrorMessage('MinionDesk: Portal URL 缺少主機名稱');
        return;
    }

    // Open web portal for longer interactions
    // NOTE: source code must NOT be sent as a URL query param (exposure risk).
    // Use a POST request body for sending code content to the portal.
    const portalUrl = new URL(parsedUrl.toString());
    portalUrl.searchParams.set('minion', targetMinion);
    // portalUrl.searchParams.set('prompt', prompt.substring(0, 200));
    // Removed: do not include source code in URL — send via POST body instead.
    const uri = vscode.Uri.parse(portalUrl.toString());

    // Show result in output channel
    outputChannel.show();
    outputChannel.appendLine(`\n[${new Date().toLocaleTimeString()}] Sending to MinionDesk (${targetMinion})...`);
    outputChannel.appendLine('Opening Web Portal for response...');

    // Open browser portal
    const opened = await vscode.env.openExternal(uri);
    if (!opened) {
        vscode.window.showErrorMessage(`MinionDesk: 無法開啟 Portal — ${serverUrl}`);
    }
}

async function askMinion(): Promise<void> {
    const question = await vscode.window.showInputBox({
        prompt: 'Ask MinionDesk IT Copilot...',
        placeHolder: 'e.g., How do I fix LSF job pending? VNC connection issue?',
    });
    if (!question) return;
    await sendToMinionDesk(question);
}

async function reviewCode(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('Please select code to review'); return; }
    const lang = getFileLanguage();
    const safeLang = escapeCodeFences(lang);
    const safeCode = escapeCodeFences(code);
    const prompt = `請對以下 ${lang} 程式碼進行 Code Review，檢查 Bug、效能問題，並確認符合 IC 設計資安規範：\n\`\`\`${safeLang}\n${safeCode}\n\`\`\``;
    await sendToMinionDesk(prompt, 'stuart');
}

async function explainCode(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('Please select code to explain'); return; }
    const lang = getFileLanguage();
    const safeLang = escapeCodeFences(lang);
    const safeCode = escapeCodeFences(code);
    const prompt = `請用白話文解釋以下 ${lang} 程式碼的功能和邏輯：\n\`\`\`${safeLang}\n${safeCode}\n\`\`\``;
    await sendToMinionDesk(prompt, 'stuart');
}

async function generateTests(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('Please select code to generate tests for'); return; }
    const lang = getFileLanguage();
    const safeLang = escapeCodeFences(lang);
    const safeCode = escapeCodeFences(code);
    const prompt = `請為以下 ${lang} 程式碼生成完整的單元測試，涵蓋正常情況、邊界條件和錯誤處理：\n\`\`\`${safeLang}\n${safeCode}\n\`\`\``;
    await sendToMinionDesk(prompt, 'stuart');
}

async function analyzeLog(): Promise<void> {
    const logContent = getSelectedText();
    if (!logContent) {
        // Ask user to paste log
        const log = await vscode.window.showInputBox({
            prompt: 'Paste your error log here',
            placeHolder: 'Paste kernel log, EDA error, or application log...',
        });
        if (!log) { return; }
        const safeLog = escapeCodeFences(log);
        await sendToMinionDesk(`請分析以下錯誤日誌，找出根本原因並給出修復建議：\n\`\`\`\n${safeLog}\n\`\`\``);
    } else {
        const safeLogContent = escapeCodeFences(logContent);
        await sendToMinionDesk(`請分析以下錯誤日誌：\n\`\`\`\n${safeLogContent}\n\`\`\``);
    }
}

async function translateScript(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('Please select script to translate'); return; }
    const lang = getFileLanguage();
    const targetLang = await vscode.window.showQuickPick(['Python', 'Go', 'Python + type hints'], {
        placeHolder: 'Translate to...',
    });
    if (!targetLang) return;
    const safeLang = escapeCodeFences(lang);
    const safeCode = escapeCodeFences(code);
    const prompt = `請將以下 ${lang} 腳本精確翻譯成 ${targetLang}，保留所有邏輯，並加上適當的錯誤處理：\n\`\`\`${safeLang}\n${safeCode}\n\`\`\``;
    await sendToMinionDesk(prompt, 'stuart');
}

export function deactivate() {
    // Cleanup handled via context.subscriptions (outputChannel disposed automatically)
}
