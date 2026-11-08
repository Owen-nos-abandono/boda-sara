(() => {
  "use strict";

  const envelope = document.getElementById("envelope");
  const contents = document.getElementById("contents");
  const hint = document.getElementById("hint");
  const rsvpForm = document.getElementById("rsvp");

  const reduceMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  // APERTURA DEL SOBRE
  if (envelope && contents && hint) {
    let invitationOpened = false;

    envelope.addEventListener("click", () => {
      if (invitationOpened) return;

      invitationOpened = true;

      envelope.classList.add("open");
      envelope.setAttribute("aria-expanded", "true");
      envelope.setAttribute("aria-label", "Invitación abierta");

      hint.innerHTML = 'Una invitación hecha con amor<span>♡</span>';

      window.setTimeout(() => {
        contents.hidden = false;

        contents.scrollIntoView({
          behavior: reduceMotion ? "auto" : "smooth",
          block: "start"
        });
      }, reduceMotion ? 80 : 1450);
    });
  }

  // CONFIRMACIÓN DE ASISTENCIA
  if (rsvpForm) {
    rsvpForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      const button = rsvpForm.querySelector('button[type="submit"]');
      const note = rsvpForm.querySelector(".form-note");

      const payload = {
        guest: document.getElementById("guest").value.trim(),
        attendance: document.getElementById("attendance").value,
        guests: Number(document.getElementById("guests").value),
        message: document.getElementById("message").value.trim()
      };

      if (!payload.guest) {
        note.textContent = "Por favor, escribe tu nombre.";
        document.getElementById("guest").focus();
        return;
      }

      button.disabled = true;
      button.textContent = "Enviando...";
      note.textContent = "";

      try {
        const response = await fetch("/api/rsvp", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (!response.ok) {
          throw new Error(
            result.detail || "No se pudo guardar tu confirmación."
          );
        }

        rsvpForm.innerHTML = `
          <div class="rsvp-success">
            <div class="divider">♡</div>
            <h3>¡Muchas gracias!</h3>
            <p>
              ${
                payload.attendance === "Sí, asistiré"
                  ? "Tu asistencia quedó registrada."
                  : "Hemos registrado tu respuesta."
              }
            </p>
            <p>
              Gracias por formar parte de este día tan especial.
            </p>
          </div>
        `;

      } catch (error) {
        note.textContent =
          error.message || "Ocurrió un error. Intenta nuevamente.";

        button.disabled = false;
        button.textContent = "Enviar confirmación";
      }
    });
  }
})();