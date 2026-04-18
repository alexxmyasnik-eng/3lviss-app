document.addEventListener('DOMContentLoaded', function() {
    
    // ----- ЭЛЕМЕНТЫ СТРАНИЦЫ -----
    const homeScreen = document.getElementById('home-screen');
    const caseDetailScreen = document.getElementById('case-detail-screen');
    const backButton = document.getElementById('back-button');
    const caseCards = document.querySelectorAll('.case-card');
    const openCaseButton = document.querySelector('#case-detail-screen .action-button');
    const balanceDisplay = document.querySelector('.user-profile .username'); // Будем показывать баланс рядом с именем

    // ----- ЭТАП 2: ИМИТАЦИЯ БЭКЕНДА И ДАННЫХ -----

    // 1. "Фальшивая" база данных пользователей. 
    // В реальности это будет на сервере, а мы для теста храним в памяти браузера.
    let fakeDatabase = {
        // Ваш Admin ID, как вы и указали
        '780434845': {
            name: 'Mikhail (Admin)',
            balance: 5000 // У админа сразу много звезд
        },
        // Для примера добавим еще одного пользователя
        '123456789': {
            name: 'Тестовый Юзер',
            balance: 100 
        }
    };
    
    // Выбираем текущего пользователя. Мы жестко задаем ВАШ ID для теста.
    // Когда приложение будет в Telegram, здесь будет реальный ID.
    const CURRENT_USER_ID = '780434845'; 
    let currentUser = fakeDatabase[CURRENT_USER_ID];

    // 2. Функция для обновления отображения баланса на экране
    function updateBalanceDisplay() {
        balanceDisplay.textContent = `${currentUser.name} | ${currentUser.balance} ⭐`;
    }

    // 3. "Мозги": функция, которая имитирует открытие кейса на сервере
    function processCaseOpening(cost) {
        // Проверяем, достаточно ли денег
        if (currentUser.balance >= cost) {
            // Списываем деньги
            currentUser.balance -= cost;
            
            // Обновляем баланс на экране
            updateBalanceDisplay();
            
            // Сообщаем "витрине", что все прошло успешно
            alert(`Кейс открыт! С вашего баланса списано ${cost} ⭐. Остаток: ${currentUser.balance} ⭐`);
            // Здесь в будущем будет запускаться анимация рулетки
            
        } else {
            // Сообщаем "витрине", что денег не хватило
            alert(`Ошибка! Чтобы открыть этот кейс, на балансе должно быть не менее ${cost} ⭐`);
        }
    }
    
    // ----- КОНЕЦ ЭТАПА 2 -----


    // ----- ЛОГИКА ПЕРЕКЛЮЧЕНИЯ ЭКРАНОВ (из прошлого шага) -----

    function showScreen(screenToShow) {
        homeScreen.classList.remove('active');
        caseDetailScreen.classList.remove('active');
        screenToShow.classList.add('active');
    }

    caseCards.forEach(card => {
        card.addEventListener('click', () => {
            showScreen(caseDetailScreen);
        });
    });

    backButton.addEventListener('click', () => {
        showScreen(homeScreen);
    });
    
    // "Оживляем" кнопку открытия кейса
    openCaseButton.addEventListener('click', () => {
        const caseCost = 222; // Стоимость кейса
        processCaseOpening(caseCost);
    });

    // ----- ИНИЦИАЛИЗАЦИЯ ПРИ ЗАПУСКЕ -----
    
    // Сразу при загрузке страницы показываем баланс
    updateBalanceDisplay(); 

});

// ----- ЭТАП 2: АДМИН-ПАНЕЛЬ -----
// Мы не можем сделать команду /addstars, но мы можем сделать функцию,
// которую вы, как админ, сможете вызвать вручную для теста.
// Чтобы ей воспользоваться:
// 1. Откройте консоль разработчика в браузере (обычно клавиша F12).
// 2. Перейдите на вкладку "Консоль" (Console).
// 3. Напишите addStars(1000) и нажмите Enter.
// 4. Ваш баланс пополнится на 1000 звезд.
function addStars(amount) {
    const db = fakeDatabase[CURRENT_USER_ID];
    db.balance += amount;
    // Имитируем, что функция находится в основном коде, и обновляем дисплей
    document.querySelector('.user-profile .username').textContent = `${db.name} | ${db.balance} ⭐`;
    console.log(`Баланс пополнен на ${amount}. Новый баланс: ${db.balance}`);
}
