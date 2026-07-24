(() => {
  "use strict";

  const dateFormatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });

  function parseDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function localizeTimes() {
    document.querySelectorAll("time[data-local-time]").forEach((element) => {
      const date = parseDate(element.dateTime);
      if (!date) {
        return;
      }
      const utcLabel = element.textContent.trim();
      const localLabel = dateFormatter.format(date);
      element.textContent = localLabel;
      element.title = utcLabel;
      element.setAttribute("aria-label", `${localLabel}; source timestamp ${utcLabel}`);
    });
  }

  function durationLabel(target, now) {
    const totalMinutes = Math.round(Math.abs(target - now) / 60000);
    if (totalMinutes < 1) {
      return target >= now ? "due now" : "forecast time passed";
    }

    const days = Math.floor(totalMinutes / 1440);
    const hours = Math.floor((totalMinutes % 1440) / 60);
    const minutes = totalMinutes % 60;
    const parts = [];
    if (days) {
      parts.push(`${days}d`);
    }
    if (hours) {
      parts.push(`${hours}h`);
    }
    if (!days && minutes) {
      parts.push(`${minutes}m`);
    }
    const duration = parts.join(" ");
    return target >= now ? `in ${duration}` : `${duration} ago`;
  }

  function updateCountdowns() {
    const now = new Date();
    let futureCount = 0;
    let recentCount = 0;
    const futureForecasts = [];
    document.querySelectorAll("[data-countdown]").forEach((element) => {
      const target = parseDate(element.dataset.countdown);
      if (!target) {
        return;
      }
      const row = element.closest(".arrival-row");
      if (target >= now) {
        futureCount += 1;
        futureForecasts.push({ target, row });
      } else {
        recentCount += 1;
      }
      const heading = row?.querySelector("h4");
      if (target < now && heading?.firstChild?.nodeType === Node.TEXT_NODE) {
        if (heading.firstChild.textContent.trim() === "Expected") {
          heading.firstChild.textContent = "Forecast time ";
          row.classList.add("arrival-passed");
        }
      }
      element.textContent = durationLabel(target, now);
      element.title =
        target >= now
          ? "Time until predicted arrival"
          : "Time since the modelled arrival time";
    });

    const health = document.querySelector("[data-feed-health]");
    const isHealthy = health?.classList.contains("feed-chip--healthy");
    const isDegraded = health?.classList.contains("feed-chip--degraded");
    if (isHealthy || isDegraded) {
      const futureValue = document.querySelector("[data-metric='future'] dd");
      const recentValue = document.querySelector("[data-metric='recent'] dd");
      if (futureValue) {
        futureValue.textContent = isHealthy
          ? String(futureCount)
          : futureCount
            ? `≥${futureCount}`
            : "Unknown";
      }
      if (recentValue) {
        recentValue.textContent = isHealthy
          ? String(recentCount)
          : recentCount
            ? `≥${recentCount}`
            : "Unknown";
      }
    }

    const hero = document.querySelector("[data-hero-arrival]");
    const heroTarget = parseDate(hero?.dataset.heroArrival);
    futureForecasts.sort((left, right) => left.target - right.target);
    const nextForecast = futureForecasts[0];
    if (
      hero &&
      heroTarget &&
      nextForecast &&
      heroTarget.getTime() !== nextForecast.target.getTime()
    ) {
      hero.dataset.heroArrival = nextForecast.target.toISOString();
      hero.classList.add("hero-signal--arrival");
      const label = hero.querySelector("small");
      const detail = hero.querySelector("p");
      const value = hero.querySelector("strong");
      const nextTime = nextForecast.row?.querySelector("time");
      if (label) {
        label.textContent = "Next modelled Earth arrival · last check";
      }
      if (detail) {
        detail.textContent = "Another future forecast remains in the CME outlook.";
      }
      if (value && nextTime) {
        value.replaceChildren(nextTime.cloneNode(true));
      }
    } else if (hero && heroTarget && heroTarget < now && !nextForecast) {
      hero.classList.remove("hero-signal--arrival");
      const label = hero.querySelector("small");
      const detail = hero.querySelector("p");
      if (label) {
        label.textContent = "Modelled arrival time · last check";
      }
      if (detail) {
        detail.textContent = "Forecast time passed; awaiting the next hourly check.";
      }
    }
  }

  function updateFreshness() {
    const indicator = document.querySelector("[data-feed-health]");
    if (!indicator) {
      return;
    }
    const generated = parseDate(indicator.dataset.generated);
    const freshHours = Number(indicator.dataset.freshHours);
    if (!generated || !Number.isFinite(freshHours) || freshHours <= 0) {
      return;
    }
    const isStale = Date.now() - generated.getTime() > freshHours * 60 * 60 * 1000;
    if (!isStale) {
      return;
    }

    indicator.classList.remove("feed-chip--healthy", "feed-chip--degraded");
    indicator.classList.add("feed-chip--stale");
    const label = indicator.querySelector(".feed-chip__label");
    if (label) {
      label.textContent = "Page data stale";
    }
    const healthMetric = document.querySelector(".metric-health");
    healthMetric?.classList.add("metric-health--degraded");
    const healthValue = healthMetric?.querySelector("dd");
    if (healthValue) {
      healthValue.textContent = "Stale";
    }
    const warning = document.querySelector("[data-stale-warning]");
    if (warning) {
      warning.hidden = false;
    }
  }

  function watchNavigation() {
    if (!("IntersectionObserver" in window)) {
      return;
    }
    const links = new Map(
      [...document.querySelectorAll(".site-nav a[href^='#']")].map((link) => [
        link.getAttribute("href").slice(1),
        link,
      ]),
    );
    const sections = [...links.keys()]
      .map((id) => document.getElementById(id))
      .filter(Boolean);
    if (!sections.length) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
        if (!visible) {
          return;
        }
        links.forEach((link, id) => {
          if (id === visible.target.id) {
            link.setAttribute("aria-current", "location");
          } else {
            link.removeAttribute("aria-current");
          }
        });
      },
      { rootMargin: "-20% 0px -65%", threshold: [0, 0.2, 0.6] },
    );
    sections.forEach((section) => observer.observe(section));
  }

  localizeTimes();
  updateCountdowns();
  updateFreshness();
  watchNavigation();
  window.setInterval(() => {
    updateCountdowns();
    updateFreshness();
  }, 30000);
})();
