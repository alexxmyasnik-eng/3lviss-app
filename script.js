const BACKEND_URL = 'http://192.168.1.89:5000'; // Убедитесь, что IP-адрес верный!

document.addEventListener('DOMContentLoaded', function() {
    const tg = window.Telegram.WebApp;
    tg.ready();

    const homeScreen = document.getElementById('home-screen'),
          caseDetailScreen = document.getElementById('case-detail-screen'),
          backButton = document.getElementById('back-button'),
          caseCards = document.querySelectorAll('.case-card'),
          openCaseButton = document.querySelector('#case-detail-screen .action-button'),
          userAvatarElement = document.querySelector('.user-profile .avatar'),
          usernameElement = document.querySelector('.user-profile .username');

    let currentUser = null;
    let currentUserId = null;

    async function fetchUserData() {
        const user = tg.initDataUnsafe.user;
        if (!user) {
            usernameElement.textContent = "Тестовый режим"; return;
        }

        currentUserId = user.id;
        const url = `${BACKEND_URL}/api/get_user_data?user_id=${currentUserId}&name=${user.first_name}`;
        
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error('Ошибка сети');
            
            const data = await response.json();
            currentUser = data;
            
            updateBalanceDisplay();
            // Отображаем аватарку, если ссылка на нее пришла с сервера
            if (currentUser.photo_url) {
                userAvatarElement.src = currentUser.photo_url;
            }

        } catch (error) {
            console.error('Ошибка подключения к серверу:', error);
            tg.showAlert('Ошибка подключения к серверу.');
        }
    }

    function updateBalanceDisplay() {
        if (currentUser) {
            usernameElement.textContent = `${currentUser.name} | ${currentUser.balance} ⭐`;
        }
    }

    // --- ОБНОВЛЕННАЯ ЛОГИКА ОТКРЫТИЯ КЕЙСА ---
    async function processCaseOpening(cost) {
        if (!currentUser) return;

        openCaseButton.disabled = true; // Блокируем кнопку на время запроса
        openCaseButton.textContent = "Открываем...";

        try {
            const response = await fetch(`${BACKEND_URL}/api/open_case`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUserId, cost: cost })
            });

            const result = await response.json();

            if (result.success) {
                // Успех! Обновляем баланс из ответа сервера
                currentUser.balance = result.new_balance;
                updateBalanceDisplay();
                tg.HapticFeedback.notificationOccurred('success');
                alert(`Выпал предмет: ${result.prize}`);
            } else {
                // Ошибка от сервера (например, нехватка денег)
                tg.HapticFeedback.notificationOccurred('error');
                alert(`Ошибка: ${result.error}`);
            }

        } catch (error) {
            console.error('Ошибка при открытии кейса:', error);
            tg.showAlert('Не удалось выполнить операцию.');
        } finally {
            openCaseButton.disabled = false; // Разблокируем кнопку
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
