// --- ВАЖНАЯ НАСТРОЙКА ---
// Вставьте сюда актуальный адрес, который выдает NGROK
const BACKEND_URL = 'https://<ВАШ_АДРЕС_NGROK>.ngrok-free.dev';
// -------------------------


document.addEventListener('DOMContentLoaded', function() {
    
    // ----- СИСТЕМА ОТЛАДКИ -----
    const debugConsole = document.getElementById('debug-console');
    function logToScreen(message) {
        const now = new Date();
        const time = `${now.getHours()}:${now.getMinutes()}:${now.getSeconds()}`;
        debugConsole.innerHTML += `<div>[${time}] ${message}</div>`;
        console.log(message);
    }
    
    logToScreen('Приложение запущено.');
    logToScreen(`Целевой URL: ${BACKEND_URL}`);

    const tg = window.Telegram.WebApp;
    tg.ready();

    // ----- ЭЛЕМЕНТЫ СТРАНИЦЫ -----
    const homeScreen = document.getElementById('home-screen'),
          caseDetailScreen = document.getElementById('case-detail-screen'),
          backButton = document.getElementById('back-button'),
          caseCards = document.querySelectorAll('.case-card'),
          openCaseButton = document.querySelector('#case-detail-screen .action-button'),
          userAvatarElement = document.querySelector('.user-profile .avatar'),
          usernameElement = document.querySelector('.user-profile .username');

    let currentUser = null;
    let currentUserId = null;

    // ----- ОСНОВНАЯ ЛОГИКА -----
    async function fetchUserData() {
        const user = tg.initDataUnsafe.user;
        if (!user) {
            logToScreen('Не в Telegram. Включен тестовый режим.');
            usernameElement.textContent = "Тестовый режим"; return;
        }

        currentUserId = user.id;
        const url = `${BACKEND_URL}/api/get_user_data?user_id=${currentUserId}&name=${user.first_name}`;
        
        logToScreen(`Запрашиваю данные с: ${url}`);

        try {
            const response = await fetch(url, { cache: 'no-cache' });
            logToScreen(`Ответ от сервера получен. Статус: ${response.status}`);

            if (!response.ok) {
                throw new Error(`Статус ответа: ${response.status}`);
            }
            
            const data = await response.json();
            logToScreen('JSON успешно разобран.');
            currentUser = data;
            
            updateBalanceDisplay();
            if (currentUser.photo_url) {
                userAvatarElement.src = currentUser.photo_url;
            }

        } catch (error) {
            logToScreen('!!! КРИТИЧЕСКАЯ ОШИБКА FETCH !!!');
            logToScreen(error.toString());
            logToScreen(`Тип ошибки: ${error.name}`);
            tg.showAlert('Ошибка подключения. Смотри детали в углу экрана.');
        }
    }

    function updateBalanceDisplay() {
        if (currentUser) {
            usernameElement.textContent = `${currentUser.name} | ${currentUser.balance} ⭐`;
        }
    }

    async function processCaseOpening(cost) {
        if (!currentUser) return;
        openCaseButton.disabled = true;
        openCaseButton.textContent = "Открываем...";
        try {
            const response = await fetch(`${BACKEND_URL}/api/open_case`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUserId, cost: cost })
            });
            const result = await response.json();
            if (result.success) {
                currentUser.balance = result.new_balance;
                updateBalanceDisplay();
                tg.HapticFeedback.notificationOccurred('success');
                alert(`Выпал предмет: ${result.prize}`);
            } else {
                tg.HapticFeedback.notificationOccurred('error');
                alert(`Ошибка: ${result.error}`);
            }
        } catch (error) {
            logToScreen('!!! ОШИБКА ОТКРЫТИЯ КЕЙСА !!!');
            logToScreen(error.toString());
            tg.showAlert('Не удалось выполнить операцию.');
        } finally {
            openCaseButton.disabled = false;
            openCaseButton.textContent = `Открыть за ${cost} ⭐`;
        }
    }

    // --- Логика интерфейса ---
    function showScreen(screen) { homeScreen.classList.remove('active'); caseDetailScreen.classList.remove('active'); screen.classList.add('active');}
    caseCards.forEach(card => card.addEventListener('click', () => showScreen(caseDetailScreen)));
    backButton.addEventListener('click', () => showScreen(homeScreen));
    openCaseButton.addEventListener('click', () => processCaseOpening(222));

    fetchUserData();
});
