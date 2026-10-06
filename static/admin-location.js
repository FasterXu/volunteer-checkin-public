(() => {
  document.querySelectorAll("[data-location-toggle]").forEach(toggle => {
    const fields = document.getElementById(toggle.dataset.locationToggle);
    if (!fields) return;

    function syncLocationFields() {
      fields.classList.toggle("is-inactive", !toggle.checked);
      fields.querySelectorAll('input[name="latitude"], input[name="longitude"]').forEach(input => {
        input.required = toggle.checked;
      });
    }

    toggle.addEventListener("change", syncLocationFields);
    syncLocationFields();
  });

  document.querySelectorAll("[data-passphrase-toggle]").forEach(toggle => {
    const fields = document.getElementById(toggle.dataset.passphraseToggle);
    const input = fields?.querySelector('input[name="passphrase"]');
    if (!fields || !input) return;

    function syncPassphraseField() {
      fields.classList.toggle("is-inactive", !toggle.checked);
      input.disabled = !toggle.checked;
      if (!toggle.checked) input.value = "";
    }

    toggle.addEventListener("change", syncPassphraseField);
    syncPassphraseField();
  });

  document.querySelectorAll(".fill-current-location").forEach(button => {
    button.addEventListener("click", () => {
      const latitudeInput = document.getElementById(button.dataset.latitudeTarget);
      const longitudeInput = document.getElementById(button.dataset.longitudeTarget);
      const status = button.parentElement.querySelector(".location-fill-status")
        || button.closest(".location-fields").querySelector(".location-fill-status");

      if (!navigator.geolocation) {
        status.textContent = "当前浏览器不支持位置服务，请手工填写经纬度。";
        return;
      }
      button.disabled = true;
      status.textContent = "正在获取当前位置…";
      navigator.geolocation.getCurrentPosition(position => {
        latitudeInput.value = position.coords.latitude.toFixed(7);
        longitudeInput.value = position.coords.longitude.toFixed(7);
        status.textContent = `已填入当前位置，定位精度约 ${Math.round(position.coords.accuracy)} 米。`;
        button.disabled = false;
      }, error => {
        const messages = {
          1: "位置权限被拒绝，请允许定位或手工填写经纬度。",
          2: "暂时无法取得位置，请手工填写或稍后重试。",
          3: "定位超时，请重试。"
        };
        status.textContent = messages[error.code] || "定位失败，请手工填写经纬度。";
        button.disabled = false;
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
    });
  });
})();
