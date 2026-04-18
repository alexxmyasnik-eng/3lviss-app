// --- ВАЖНАЯ НАСТРОЙКА ---
// Вставьте сюда IP-адрес вашего компьютера из консоли Python
const BACKEND_URL = 'http://192.168.1.89:5000';
// -------------------------


document.addEventListener('DOMContentLoaded', function() {
    
    const tg = window.Telegram.WebApp;
    tg.ready();

    // Элементы страницы
    const homeScreen = document.getElementById('home-screen');
    const caseDetailScreen = document.getElementById('case-detail-screen');
    const backButton = document.getElementById('back-button');
    const caseCards = document.querySelectorAll('.case-card');
    const openCaseButton = document.querySelector('#case-detail-screen .action-button');
    const userAvatarElement = document.querySelector('.user-profile .avatar');
    const usernameElement = document.querySelector('.user-profile .username');

    let currentUser = null; // Здесь будут храниться данные о пользователе
    let currentUserId = null;

    // Функция для получения данных с нашего Python-сервера
    async function fetchUserData() {
        if (!tg.initDataUnsafe.user) {
            usernameElement.textContent = "Тестовый режим (вне Telegram)";
            return;
        }

        currentUserId = tg.initDataUnsafe.user.id;
        const url = `${BACKEND_URL}/api/get_user_data?user_id=${currentUserId}`;
        
        try {
            // Отправляем запрос на наш Python-сервер
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`Ошибка сети: ${response.status}`);
            }

            // Получаем данные в формате JSON
            const data = await response.json();
            currentUser = data; // Сохраняем данные
            
            // Обновляем интерфейс
            updateBalanceDisplay();

        } catch (error) {
            // Если сервер не доступен, показываем ошибку
            console.error('Не удалось подключиться к серверу:', error);
            usernameElement.textContent = "Ошибка подключения к серверу";
            tg.showAlert('Не удалось подключиться к серверу. Убедитесь, что вы в одной Wi-Fi сети с компьютером, на котором запущен сервер.');
        }
    }

    function updateBalanceDisplay() {
        if (currentUser) {
            usernameElement.textContent = `${currentUser.name} | ${currentUser.balance} ⭐`;
        }
    }

    // "Мозги" теперь тоже обращаются к серверу (мы сделаем это на след. шаге)
    function processCaseOpening(cost) {
        // Пока оставляем старую логику, но с новыми данными
        if (currentUser.balance >= cost) {
            // В будущем здесь будет запрос к серверу на списание
            currentUser.balance -= cost; 
            updateBalanceDisplay();
            tg.HapticFeedback.notificationOccurred('success');
            alert(`Кейс открыт! Остаток: ${currentUser.balance} ⭐`);
        } else {
            tg.HapticFeedback.notificationOccurred('error');
            alert(`Ошибка! Недостаточно средств. Нужно: ${cost} ⭐`);
        }
    }

    // --- Логика интерфейса ---
    function showScreen(screenToShow) {
        homeScreen.classList.remove('active'); caseDetailScreen.classList.remove('active');
        screenToShow.classList.add('active');
    }
    caseCards.forEach(card => card.addEventListener('click', () => showScreen(caseDetailScreen)));
    backButton.addEventListener('click', () => showScreen(homeScreen));
    openCaseButton.addEventListener('click', () => {
        const caseCost = 222;
        processCaseOpening(caseCost);
    });

    // --- Запускаем все при старте ---
    fetchUserData();
});
