(() => {
  const thread = document.getElementById("thread");
  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const subjectTabs = document.querySelectorAll("#subject-tabs .tab");
  const gradeTabs = document.querySelectorAll("#grade-tabs .tab");
  const resetBtn = document.getElementById("reset-btn");
  const chipTpl = document.getElementById("tpl-source-chip");

  let activeSubject = "all";
  let activeGrade = "all";
  let busy = false;

  subjectTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      subjectTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeSubject = tab.dataset.subject;
    });
  });

  gradeTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      gradeTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeGrade = tab.dataset.grade;
    });
  });

  resetBtn.addEventListener("click", async () => {
    await fetch("/api/reset", { method: "POST" });
    thread.innerHTML = "";
    appendModelStatic("Session cleared. Ask me anything from your NCERT chapters.");
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    input.style.height = "auto";
    appendUser(text);
    askModel(text);
  });

  function appendUser(text) {
    const el = document.createElement("div");
    el.className = "msg msg-user";
    el.innerHTML = `
      <div class="msg-avatar">You</div>
      <div class="msg-body"><div class="msg-text"></div></div>`;
    el.querySelector(".msg-text").textContent = text;
    thread.appendChild(el);
    scrollToBottom();
  }

  function appendModelStatic(text) {
    const el = document.createElement("div");
    el.className = "msg msg-model";
    el.innerHTML = `
      <div class="msg-avatar">M</div>
      <div class="msg-body"><div class="msg-text"></div></div>`;
    el.querySelector(".msg-text").textContent = text;
    thread.appendChild(el);
    scrollToBottom();
  }

  function scrollToBottom() {
    thread.scrollTop = thread.scrollHeight;
  }

  function setBusy(state) {
    busy = state;
    sendBtn.disabled = state;
  }

  async function askModel(question) {
    setBusy(true);

    const wrap = document.createElement("div");
    wrap.className = "msg msg-model";
    wrap.innerHTML = `
      <div class="msg-avatar">M</div>
      <div class="msg-body">
        <div class="warning-box"></div>
        <div class="msg-text streaming"></div>
        <div class="sources"></div>
        <div class="src-panel"></div>
      </div>`;
    thread.appendChild(wrap);
    scrollToBottom();

    const textEl = wrap.querySelector(".msg-text");
    const warnEl = wrap.querySelector(".warning-box");
    const sourcesEl = wrap.querySelector(".sources");
    const panelEl = wrap.querySelector(".src-panel");

    let raw = "";
    let sources = [];

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, subject: activeSubject, grade: activeGrade }),
      });

      if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({}));
        textEl.textContent = err.error || "Something went wrong. Please try again.";
        textEl.classList.remove("streaming");
        setBusy(false);
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          handleEvent(rawEvent);
        }
      }
    } catch (err) {
      textEl.textContent = "Connection lost. Please try again.";
    } finally {
      textEl.classList.remove("streaming");
      setBusy(false);
      renderMath(textEl);
    }

    function handleEvent(rawEvent) {
      const lines = rawEvent.split("\n");
      let event = "message", data = "{}";
      for (const line of lines) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        if (line.startsWith("data: ")) data = line.slice(6);
      }
      let payload;
      try { payload = JSON.parse(data); } catch { payload = {}; }

      if (event === "meta" && payload.warning) {
        warnEl.innerHTML = `<div class="warning-banner">${escapeHtml(payload.warning)}</div>`;
      } else if (event === "sources") {
        sources = payload.sources || [];
        renderSourceChips(sources, sourcesEl, panelEl);
      } else if (event === "token") {
        raw += payload.text;
        textEl.innerHTML = renderMarkdown(raw);
        scrollToBottom();
      } else if (event === "error") {
        textEl.textContent = payload.message || "Something went wrong.";
      }
    }

    function renderSourceChips(sources, sourcesEl, panelEl) {
      sourcesEl.innerHTML = "";
      if (!sources.length) return;
      sources.forEach(s => {
        const chip = chipTpl.content.firstElementChild.cloneNode(true);
        chip.textContent = `[${s.n}] p.${s.page}`;
        chip.addEventListener("click", () => {
          const isOpen = panelEl.classList.contains("open") && panelEl.dataset.n === String(s.n);
          if (isOpen) {
            panelEl.classList.remove("open");
            return;
          }
          panelEl.dataset.n = s.n;
          // Build panel content: text, images, and models
          let inner = `<b>[${s.n}] Class ${escapeHtml(s.grade)} ${escapeHtml(s.subject)} — ${escapeHtml(s.chapter)}</b><br>
            Page ${s.page} · ${escapeHtml(s.source_file)} · relevance ${s.score}`;
          if (s.images && s.images.length > 0) {
            inner += "<br><br><strong>Images:</strong><br>";
            s.images.forEach(imgUrl => {
              inner += `<img src="${imgUrl}" alt="Illustration from page ${s.page}" style="max-width:100%; height:auto; margin-top:4px; border-radius:4px;">`;
            });
          }
          if (s.models && s.models.length > 0) {
            inner += "<br><br><strong>3D Models:</strong><br>";
            s.models.forEach((modelUrl, index) => {
              const modelId = `model-${s.n}-${index}`;
              inner += `<div id="${modelId}" style="width:100%; height:300px; margin-top:8px; border:1px solid #ccc; border-radius:4px;"></div>`;
            });
          }
          panelEl.innerHTML = inner;
          panelEl.classList.add("open");

          // Initialize 3D viewers for each model
          if (s.models && s.models.length > 0) {
            s.models.forEach((modelUrl, index) => {
              const modelId = `model-${s.n}-${index}`;
              const container = document.getElementById(modelId);
              if (container) {
                initModelViewer(container, modelUrl);
              }
            });
          }
        });
        sourcesEl.appendChild(chip);
      });
    }

    function initModelViewer(container, modelUrl) {
      // If the container is not visible, we might need to resize later, but we'll handle via window resize
      if (!container) return;

      // Create a three.js scene
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf0f0f0);

      const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
      camera.position.set(0, 1.5, 3);
      camera.lookAt(0, 0, 0);

      const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444);
      hemiLight.position.set(0, 20, 0);
      scene.add(hemiLight);

      const dirLight = new THREE.DirectionalLight(0xffffff);
      dirLight.position.set(-3, 10, -10);
      dirLight.position.normalize();
      scene.add(dirLight);

      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(container.clientWidth, container.clientHeight);
      container.appendChild(renderer.domElement);

      // Load the model
      let loader;
      const lowerUrl = modelUrl.toLowerCase();
      if (lowerUrl.endsWith('.glb') || lowerUrl.endsWith('.gltf')) {
        loader = new THREE.GLTFLoader();
      } else if (lowerUrl.endsWith('.obj')) {
        loader = new THREE.OBJLoader();
      } else {
        container.textContent = 'Unsupported model format';
        return;
      }

      loader.load(
        modelUrl,
        object => {
          scene.add(object);
        },
        xhr => {
          // Loading progress (optional)
          // console.log((xhr.loaded / xhr.total * 100) + '% loaded');
        },
        error => {
          console.error('Error loading model:', error);
          container.textContent = 'Failed to load model';
        }
      );

      const controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;

      function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      }
      animate();

      // Handle window resize
      window.addEventListener('resize', () => {
        const width = container.clientWidth;
        const height = container.clientHeight;
        renderer.setSize(width, height);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      });
    }

    // --- minimal markdown (bold/italic/code/lists/paragraphs) ---
    function renderMarkdown(src) {
      let s = escapeHtml(src);
      s = s.replace(/```([\s\S]*?)```/g, (_, code) => `<pre><code>${code}</code></pre>`);
      s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
      s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
      s = s.replace(/^\s*-\s+(.*)$/gm, "<li>$1</li>");
      s = s.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
      s = s.split(/\n{2,}/).map(block => {
        if (/^<(ul|pre)/.test(block.trim())) return block;
        return `<p>${block.replace(/\n/g, "<br>")}</p>`;
      }).join("\n");
      return s;
    }

    function escapeHtml(str) {
      return str.replace(/[&<>"']/g, (c) => ({
        "&": "&", "<": "<", ">": ">", '"': """, "'": "'",
      }[c]));
    }

    function renderMath(el) {
      if (window.renderMathInElement) {
        window.renderMathInElement(el, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
          ],
          throwOnError: false,
        });
      }
    }
  })();