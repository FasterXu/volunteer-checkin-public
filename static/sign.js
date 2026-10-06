(() => {
  function startConfetti() {
    const successMessage = document.querySelector(".result-success");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!successMessage || reduceMotion) return;

    const colors = ["#A40006", "#009944", "#F39800", "#004098", "#7E3C93", "#E8BA41"];
    const layer = document.createElement("div");
    layer.className = "confetti-layer";
    layer.setAttribute("aria-hidden", "true");

    for (let index = 0; index < 56; index += 1) {
      const piece = document.createElement("i");
      const width = 5 + Math.random() * 6;
      const duration = 2.5 + Math.random() * 1.3;
      piece.className = "confetti-piece";
      piece.style.setProperty("--confetti-left", `${Math.random() * 100}%`);
      piece.style.setProperty("--confetti-width", `${width}px`);
      piece.style.setProperty("--confetti-height", `${width * (0.8 + Math.random() * 1.2)}px`);
      piece.style.setProperty("--confetti-color", colors[index % colors.length]);
      piece.style.setProperty("--confetti-radius", index % 4 === 0 ? "50%" : "1px");
      piece.style.setProperty("--confetti-delay", `${Math.random() * 0.7}s`);
      piece.style.setProperty("--confetti-duration", `${duration}s`);
      piece.style.setProperty("--confetti-drift", `${-90 + Math.random() * 180}px`);
      piece.style.setProperty("--confetti-spin", `${360 + Math.random() * 720}deg`);
      layer.appendChild(piece);
    }

    document.body.appendChild(layer);
    successMessage.classList.add("success-celebrate");
    window.setTimeout(() => layer.remove(), 4600);
  }

  function distanceInMeters(latitude1, longitude1, latitude2, longitude2) {
    const earthRadius = 6371000;
    const toRadians = degrees => degrees * Math.PI / 180;
    const lat1 = toRadians(latitude1);
    const lat2 = toRadians(latitude2);
    const deltaLat = toRadians(latitude2 - latitude1);
    const deltaLon = toRadians(longitude2 - longitude1);
    const haversine = Math.sin(deltaLat / 2) ** 2
      + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
    return earthRadius * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
  }

  function setupVerificationFlow() {
    const form = document.getElementById("signForm");
    if (!form) return;

    const locationRequired = form.dataset.locationRequired === "true";
    const passphraseRequired = form.dataset.passphraseRequired === "true";
    if (!locationRequired && !passphraseRequired) return;

    const identityStep = document.getElementById("identityStep");
    const identityContent = document.getElementById("identityStepContent");
    const identityToggle = document.getElementById("identityStepToggle");
    const locationStep = document.getElementById("locationStep");
    const locationContent = document.getElementById("locationStepContent");
    const locationToggle = document.getElementById("locationStepToggle");
    const passphraseStep = document.getElementById("passphraseStep");
    const passphraseContent = document.getElementById("passphraseStepContent");
    const passphraseToggle = document.getElementById("passphraseStepToggle");
    const firstContinueButton = document.getElementById(
      locationRequired ? "continueToLocation" : "continueToPassphrase"
    );
    const completeButton = document.getElementById("completeSign");

    function setExpanded(step, expanded) {
      if (!step) return;
      const content = step === identityStep
        ? identityContent
        : (step === locationStep ? locationContent : passphraseContent);
      const toggle = step === identityStep
        ? identityToggle
        : (step === locationStep ? locationToggle : passphraseToggle);
      content.hidden = !expanded;
      step.classList.toggle("is-open", expanded);
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.querySelector(".step-chevron").textContent = expanded ? "−" : "＋";
    }

    function openOnly(step, scroll = true) {
      setExpanded(identityStep, step === identityStep);
      if (locationStep) setExpanded(locationStep, step === locationStep);
      if (passphraseStep) setExpanded(passphraseStep, step === passphraseStep);
      if (scroll) step.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function unlock(step, toggle) {
      toggle.disabled = false;
      step.classList.remove("is-locked");
      if (step === passphraseStep) {
        document.getElementById("signPassphrase").disabled = form.dataset.active !== "true";
      }
    }

    function identityIsValid() {
      const controls = [...identityContent.querySelectorAll("input, textarea, select")];
      const invalidControl = controls.find(control => !control.checkValidity());
      if (invalidControl) {
        invalidControl.reportValidity();
        return false;
      }
      return true;
    }

    identityToggle.addEventListener("click", () => {
      if (identityContent.hidden) {
        openOnly(identityStep);
      } else {
        setExpanded(identityStep, false);
      }
    });

    firstContinueButton.addEventListener("click", () => {
      if (!identityIsValid()) return;
      const nextStep = locationRequired ? locationStep : passphraseStep;
      const nextToggle = locationRequired ? locationToggle : passphraseToggle;
      unlock(nextStep, nextToggle);
      openOnly(nextStep);
    });

    if (locationRequired) {
      const backButton = document.getElementById("backToIdentity");
      const requestButton = document.getElementById("requestLocation");
      const continueAfterLocation = document.getElementById("continueAfterLocation");
      const locationAction = continueAfterLocation || completeButton;
      const result = document.getElementById("locationResult");
      const latitudeInput = document.getElementById("signLatitude");
      const longitudeInput = document.getElementById("signLongitude");
      const accuracyInput = document.getElementById("signLocationAccuracy");
      const targetLatitude = Number(form.dataset.targetLatitude);
      const targetLongitude = Number(form.dataset.targetLongitude);
      const allowedRadius = Number(form.dataset.locationRadius);

      function showResult(kind, message) {
        result.className = `location-result ${kind}`;
        result.textContent = message;
      }

      locationToggle.addEventListener("click", () => {
        if (locationToggle.disabled) return;
        locationContent.hidden ? openOnly(locationStep) : setExpanded(locationStep, false);
      });

      backButton.addEventListener("click", () => openOnly(identityStep));

      if (continueAfterLocation) {
        continueAfterLocation.addEventListener("click", () => {
          unlock(passphraseStep, passphraseToggle);
          openOnly(passphraseStep);
          document.getElementById("signPassphrase").focus();
        });
      }

      requestButton.addEventListener("click", () => {
        if (!navigator.geolocation) {
          showResult("danger", "当前浏览器不支持位置服务，请更换浏览器或联系管理员补签。");
          return;
        }
        requestButton.disabled = true;
        locationAction.disabled = true;
        showResult("loading", "正在获取当前位置，请保持页面开启…");

        navigator.geolocation.getCurrentPosition(position => {
          const { latitude, longitude, accuracy } = position.coords;
          const distance = distanceInMeters(targetLatitude, targetLongitude, latitude, longitude);
          latitudeInput.value = latitude;
          longitudeInput.value = longitude;
          accuracyInput.value = accuracy;
          requestButton.disabled = false;
          requestButton.textContent = "重新获取位置";

          if (distance <= allowedRadius) {
            showResult(
              "success",
              `位置核验通过：距签到点约 ${Math.round(distance)} 米，定位精度约 ${Math.round(accuracy)} 米。`
            );
            locationAction.disabled = false;
          } else {
            showResult(
              "danger",
              `当前位置距签到点约 ${Math.round(distance)} 米，超出允许的 ${Math.round(allowedRadius)} 米范围。`
            );
          }
        }, error => {
          requestButton.disabled = false;
          const messages = {
            1: "位置权限被拒绝，请在浏览器设置中允许定位后重试。",
            2: "暂时无法取得位置，请移动到信号较好的区域后重试。",
            3: "定位超时，请重试。"
          };
          showResult("danger", messages[error.code] || "定位失败，请稍后重试。");
        }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
      });
    }

    if (passphraseRequired) {
      const passphraseInput = document.getElementById("signPassphrase");
      const passphraseEntry = document.getElementById("passphraseEntry");
      const passphraseCells = [...document.querySelectorAll(".passphrase-cell")];
      const passphraseProgress = document.getElementById("passphraseProgress");
      const backButton = document.getElementById("backFromPassphrase");
      const expectedLength = Number(form.dataset.passphraseLength);

      function syncPassphrase() {
        const characters = Array.from(passphraseInput.value).slice(0, expectedLength);
        passphraseInput.value = characters.join("");
        passphraseCells.forEach((cell, index) => {
          cell.textContent = characters[index] || "";
          cell.classList.toggle("is-filled", index < characters.length);
        });
        const isComplete = characters.length === expectedLength;
        completeButton.disabled = !isComplete;
        passphraseEntry.classList.toggle("is-complete", isComplete);
        passphraseProgress.textContent = isComplete
          ? "口令已填写完整，可以提交核验"
          : `已输入 ${characters.length} / ${expectedLength} 个字符`;
      }

      passphraseToggle.addEventListener("click", () => {
        if (passphraseToggle.disabled) return;
        if (passphraseContent.hidden) {
          openOnly(passphraseStep);
          passphraseInput.focus();
        } else {
          setExpanded(passphraseStep, false);
        }
      });
      passphraseEntry.addEventListener("click", () => passphraseInput.focus());
      passphraseInput.addEventListener("input", syncPassphrase);
      passphraseInput.addEventListener("compositionend", syncPassphrase);
      backButton.addEventListener("click", () => {
        openOnly(locationRequired ? locationStep : identityStep);
      });
      syncPassphrase();
    }

    form.addEventListener("submit", event => {
      if (passphraseRequired) {
        const enteredLength = Array.from(document.getElementById("signPassphrase").value).length;
        if (enteredLength !== Number(form.dataset.passphraseLength)) {
          event.preventDefault();
          return;
        }
      }
      completeButton.disabled = true;
      completeButton.textContent = "正在核验并签到…";
    });
  }

  startConfetti();
  setupVerificationFlow();
})();
