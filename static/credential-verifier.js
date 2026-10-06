(() => {
  const config = window.CREDENTIAL_VERIFY_CONFIG;
  const drawer = document.getElementById("credentialVerifier");
  if (!config || !drawer) return;

  const toggleButton = document.getElementById("toggleCredentialVerifier");
  const closeButton = document.getElementById("closeCredentialVerifier");
  const form = document.getElementById("credentialVerifyForm");
  const input = document.getElementById("credentialScanInput");
  const startCameraButton = document.getElementById("startCredentialCamera");
  const stopCameraButton = document.getElementById("stopCredentialCamera");
  const cameraElement = document.getElementById("credentialCamera");
  const result = document.getElementById("credentialVerifyResult");
  const resultIcon = document.getElementById("credentialResultIcon");
  const resultTitle = document.getElementById("credentialResultTitle");
  const resultMessage = document.getElementById("credentialResultMessage");
  const resultDetails = document.getElementById("credentialResultDetails");
  let scanner = null;
  let cameraRunning = false;
  let scanLocked = false;

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    });
  }

  function showResult(kind, title, message, credential = null) {
    result.hidden = false;
    result.className = `credential-verify-result ${kind}`;
    resultIcon.textContent = kind === "success" ? "✓" : (kind === "loading" ? "…" : "!");
    resultTitle.textContent = title;
    resultMessage.textContent = message;
    resultDetails.hidden = !credential;
    if (!credential) return;
    document.getElementById("verifiedName").textContent = credential.name || "—";
    document.getElementById("verifiedIdentifier").textContent = credential.identifier || "—";
    document.getElementById("verifiedTime").textContent = formatTime(credential.sign_time);
    document.getElementById("verifiedAttendance").textContent = credential.attendance_status_text || "—";
    document.getElementById("verifiedAssignment").textContent =
      [credential.shift, credential.position].filter(Boolean).join(" / ") || "—";
  }

  async function verify(value) {
    const submitted = String(value || "").trim();
    if (!submitted) {
      showResult("danger", "无法核验", "请扫描电子凭证二维码，或在输入框中粘贴凭证内容。");
      input.focus();
      return;
    }
    showResult("loading", "正在核验", "正在向服务器确认当前签到状态…");
    try {
      const response = await fetch(config.verifyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ value: submitted })
      });
      const payload = await response.json();
      if (response.ok && payload.ok) {
        showResult("success", "核验通过", payload.message, payload.credential);
      } else {
        showResult("danger", "核验未通过", payload.message || "凭证无效。", payload.credential || null);
      }
    } catch (error) {
      showResult("danger", "核验失败", "网络连接异常，请检查网络后重试。");
    } finally {
      input.select();
    }
  }

  async function stopCamera() {
    if (scanner && cameraRunning) {
      try {
        await scanner.stop();
      } catch (error) {
        // Camera may already have stopped after a successful scan.
      }
    }
    if (scanner) {
      try { scanner.clear(); } catch (error) { /* No rendered scanner to clear. */ }
    }
    scanner = null;
    cameraRunning = false;
    scanLocked = false;
    cameraElement.hidden = true;
    startCameraButton.hidden = false;
    stopCameraButton.hidden = true;
  }

  async function startCamera() {
    if (typeof window.Html5Qrcode !== "function") {
      showResult("danger", "无法启动摄像头", "扫码组件加载失败，请刷新页面；也可以使用外接扫码器或粘贴凭证内容。");
      return;
    }
    startCameraButton.disabled = true;
    cameraElement.hidden = false;
    showResult("loading", "正在启动摄像头", "请允许浏览器使用摄像头，并将凭证二维码置于取景框内。");
    try {
      scanner = new window.Html5Qrcode("credentialCamera", {
        formatsToSupport: [window.Html5QrcodeSupportedFormats.QR_CODE],
        verbose: false
      });
      cameraRunning = true;
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 240, height: 240 }, aspectRatio: 1 },
        async decodedText => {
          if (scanLocked) return;
          scanLocked = true;
          input.value = decodedText;
          await stopCamera();
          await verify(decodedText);
        },
        () => {}
      );
      startCameraButton.hidden = true;
      stopCameraButton.hidden = false;
      result.hidden = true;
    } catch (error) {
      await stopCamera();
      showResult("danger", "摄像头启动失败", "请确认已授予摄像头权限，并使用 HTTPS 页面；也可以改用外接扫码器。");
    } finally {
      startCameraButton.disabled = false;
    }
  }

  function setDrawer(open) {
    drawer.hidden = !open;
    toggleButton.setAttribute("aria-expanded", String(open));
    if (open) {
      drawer.scrollIntoView({ behavior: "smooth", block: "nearest" });
      window.setTimeout(() => input.focus(), 180);
    } else {
      stopCamera();
    }
  }

  toggleButton.setAttribute("aria-controls", "credentialVerifier");
  toggleButton.setAttribute("aria-expanded", "false");
  toggleButton.addEventListener("click", () => setDrawer(drawer.hidden));
  closeButton.addEventListener("click", () => setDrawer(false));
  form.addEventListener("submit", event => {
    event.preventDefault();
    verify(input.value);
  });
  startCameraButton.addEventListener("click", startCamera);
  stopCameraButton.addEventListener("click", stopCamera);
  window.addEventListener("pagehide", stopCamera);
})();
