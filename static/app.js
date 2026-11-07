const { createApp } = Vue;

const BPMN_TASKS = [
  ['T1', 'Điền khảo sát', 'KH'],
  ['T2', 'Lưu hồ sơ khách hàng', 'SYS'],
  ['T3', 'Sàng lọc sức khỏe', 'SYS'],
  ['T4', 'Phân loại mục tiêu tập luyện', 'AI'],
  ['T5', 'Xác nhận mục tiêu & thể trạng', 'TV'],
  ['T6', 'Lập báo giá gói tập', 'SYS'],
  ['TV', 'Xem báo giá và chọn gói', 'KH'],
  ['TD', 'Tư vấn chuyên sâu', 'TV'],
  ['TX', 'Ghi nhận lựa chọn của khách', 'SYS'],
  ['TL', 'Lưu hồ sơ khách hàng tiềm năng', 'SYS'],
  ['TS', 'Chấm điểm và lọc PT', 'SYS'],
  ['TM', 'Phân bổ PT thủ công', 'QL'],
  ['TA', 'Đề xuất PT hoặc giờ khác', 'SYS'],
  ['TQ', 'Khóa tạm lịch PT', 'SYS'],
  ['TC', 'Tạo hợp đồng điện tử', 'SYS'],
  ['TSG', 'Xem và ký hợp đồng', 'KH'],
  ['TNR', 'Gửi nhắc ký hợp đồng', 'SYS'],
  ['TR_Slot', 'Giải phóng slot PT đã giữ', 'SYS'],
  ['TPAY', 'Thanh toán trực tuyến', 'KH'],
  ['TVF', 'Xác thực thanh toán', 'SYS'],
  ['TRP', 'Gửi liên kết thanh toán lại', 'SYS'],
  ['TR', 'Giải phóng lịch PT đã khóa', 'SYS'],
  ['TCD', 'Kích hoạt thẻ hội viên', 'SYS'],
  ['TI', 'Xuất hóa đơn điện tử', 'SYS'],
  ['TN', 'Gửi thông báo PT và lịch buổi đầu', 'SYS'],
  ['TP', 'Xác nhận lịch & lập phác đồ sơ bộ', 'PT'],
  ['ES1', 'Giải phóng lịch PT', 'SYS'],
  ['ES2', 'Ghi nhận lý do hủy', 'SYS'],
].map(([id, name, lane]) => ({ id, name, lane }));

window.activeLifeApp = createApp({
  data() {
    return {
      loading: false,
      authenticated: false,
      user: null,
      loginError: '',
      loginForm: { username: '', password: '' },
      demoUsers: [
        { username: 'customer', password: 'Member@123', label: 'Khách hàng' },
        { username: 'consultant', password: 'Consult@123', label: 'Tư vấn viên' },
        { username: 'manager', password: 'Manager@123', label: 'Quản lý PT' },
        { username: 'pt', password: 'Trainer@123', label: 'Huấn luyện viên PT' },
        { username: 'admin', password: 'Admin@123', label: 'Quản trị viên' },
      ],
      role: 'customer',
      step: 1,
      questions: [],
      labels: {
        WEIGHT_LOSS: 'Giảm cân & giảm mỡ',
        MUSCLE_GAIN: 'Tăng cơ & thể hình',
        REHAB: 'Phục hồi & vận động',
        GENERAL_FITNESS: 'Thể lực tổng quát',
      },
      styleLabels: { STRICT: 'Kỷ luật', MOTIVATIONAL: 'Động viên', GENTLE: 'Nhẹ nhàng' },
      tasks: BPMN_TASKS,
      process: null,
      currentTask: 'T1',
      done: [],
      form: {
        full_name: '', phone: '', email: '', date_of_birth: '', gender: '',
        raw_goal_text: '', coaching_style: 'MOTIVATIONAL', parq_answers: Array(7).fill(false),
      },
      survey: null,
      packages: [],
      packageName: 'CLASSIC',
      months: 3,
      quote: {},
      trainerCandidates: [],
      contract: {},
      signature: '',
      agree: false,
      payMethod: 'VNPAY',
      paid: false,
      paymentFailed: false,
      cancelled: false,
      invoiceNumber: '',
      pending: [],
      pendingConsults: [],
      consultantResponses: {},
      review: null,
      verifyGoal: 'GENERAL_FITNESS',
      reviewNotes: '',
      unassigned: [],
      allTrainers: [],
      assignments: {},
      managerSlots: {},
      selectedSlots: {},
      schedule: [],
      ptNotes: {},
      overview: {},
      packagePrices: {},
      toastText: '',
      toastTimer: null,
    };
  },
  computed: {
    roleLabel() {
      return { customer: 'Khách hàng', consultant: 'Tư vấn viên', manager: 'Quản lý PT', pt: 'Huấn luyện viên PT', admin: 'Admin' }[this.role];
    },
    kicker() { return this.role === 'customer' ? `BƯỚC ${String(this.step).padStart(2, '0')}` : 'WORKSPACE'; },
    title() {
      if (this.role === 'customer') return ['', 'Hãy làm quen nhé', 'Mục tiêu & thể trạng', 'Báo giá và lịch PT', 'Lịch tập & hợp đồng', 'Thanh toán & kích hoạt'][this.step];
      return { consultant: 'Hàng đợi xác nhận mục tiêu', manager: 'Phân bổ huấn luyện viên', pt: 'Lịch tập và xác nhận ca', admin: 'Tổng quan hệ thống' }[this.role];
    },
    subtitle() {
      if (this.role === 'customer') return ['', 'Chia sẻ thông tin để đội ngũ xây dựng kế hoạch tập luyện phù hợp.', 'Hoàn tất xác nhận mục tiêu trước khi xem báo giá.', 'Chọn gói trước; gói có PT sẽ đi qua bước ghép và chọn ca.', 'Theo dõi lịch PT xác nhận, sau đó xem và ký hợp đồng.', 'Thanh toán demo và kích hoạt thẻ hội viên.'][this.step];
      return {
        consultant: 'Xem các ca dưới ngưỡng tin cậy và xác nhận mục tiêu tại T5.',
        manager: 'Chỉ nhận hồ sơ đã qua các lần ghép tự động nhưng chưa bố trí được PT.',
        pt: 'Xác nhận hoặc từ chối ca tập đầu tiên đang được giữ cho bạn.',
        admin: 'Đối soát thanh toán, PT và số liệu hội viên.',
      }[this.role];
    },
    packageLabel() {
      return this.packages.find((p) => p.id === this.contract.package_name)?.name || this.packages.find((p) => p.id === this.packageName)?.name || this.packageName;
    },
    completedTaskCount() { return this.tasks.filter((t) => this.done.includes(t.id)).length; },
    currentTaskLabel() {
      const task = this.tasks.find((t) => t.id === this.currentTask);
      if (task) return `${task.id} · ${task.name}`;
      return { E1: 'Kết thúc · Đã lưu hồ sơ tiềm năng', E2: 'Kết thúc · Khách không ký', E3: 'Kết thúc · Đăng ký hoàn tất', ESe: 'Kết thúc · Đăng ký đã hủy' }[this.currentTask] || 'T1 · Điền khảo sát';
    },
  },
  async mounted() { await this.bootstrap(); },
  methods: {
    async api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      });
      let data = {};
      try { data = await response.json(); } catch { /* empty response */ }
      if (!response.ok) {
        let detail = data.detail;
        if (Array.isArray(detail)) detail = detail.map((item) => item.msg).join('; ');
        throw new Error(detail || `Máy chủ trả lỗi HTTP ${response.status}.`);
      }
      return data;
    },
    async busy(action) {
      this.loading = true;
      try { return await action(); }
      catch (error) { this.notify(error.message || 'Không thể kết nối máy chủ.'); return null; }
      finally { this.loading = false; }
    },
    async bootstrap() {
      try {
        this.user = await this.api('/api/auth/me');
        this.authenticated = true;
        this.role = this.user.role;
        await this.refreshRole();
      } catch { this.authenticated = false; }
    },
    fillLogin(user) { this.loginForm = { username: user.username, password: user.password }; this.loginError = ''; },
    async login() {
      this.loading = true;
      this.loginError = '';
      try {
        this.user = await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.loginForm) });
        this.authenticated = true;
        this.role = this.user.role;
        await this.refreshRole();
        this.notify(`Xin chào ${this.user.name}`);
      } catch (error) { this.loginError = error.message; }
      finally { this.loading = false; }
    },
    async logout() {
      try { await this.api('/api/auth/logout', { method: 'POST' }); } catch { /* session may already be expired */ }
      this.authenticated = false;
      this.user = null;
      this.loginError = '';
      this.loginForm = { username: '', password: '' };
    },
    notify(message) {
      this.toastText = message;
      clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => { this.toastText = ''; }, 3800);
    },
    money(amount) { return new Intl.NumberFormat('vi-VN').format(amount || 0) + ' ₫'; },
    initials(name) { return (name || 'AL').split(' ').slice(-2).map((word) => word[0]).join(''); },
    formatDate(value) {
      if (!value) return 'Chưa xếp lịch';
      return new Intl.DateTimeFormat('vi-VN', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(`${value}T00:00:00`));
    },
    formatDateTime(value) { return value ? new Date(value).toLocaleString('vi-VN') : 'Không áp dụng'; },
    async loadQuestions() {
      const result = await this.api('/api/survey/questions');
      this.questions = result.questions;
    },
    async refreshProcess() {
      const cases = await this.api('/api/customer/processes');
      if (!cases.length) {
        this.process = null; this.survey = null; this.contract = {}; this.currentTask = 'T1'; this.done = []; this.step = 1;
        return;
      }
      const retryContractId = Number(new URLSearchParams(window.location.search).get('retry_contract_id'));
      const item = cases.find((entry) => retryContractId && entry.contract_id === retryContractId) || cases[0];
      this.process = item;
      this.currentTask = item.current_task || 'T1';
      try { this.done = JSON.parse(item.completed_tasks || '[]'); } catch { this.done = []; }
      this.survey = {
        survey_id: item.survey_id,
        predicted_goal: item.predicted_goal,
        raw_goal_text: item.raw_goal_text,
        confidence_score: item.confidence_score || 0,
        medical_alert: Boolean(item.medical_alert),
        ai_status: item.ai_status,
        status: item.ai_status,
      };
      this.packageName = item.package_name || item.contract_package || 'CLASSIC';
      this.months = item.months || item.contract_months || 3;
      this.contract = item.contract_id ? {
        contract_id: item.contract_id,
        contract_code: item.contract_code,
        contract_status: item.contract_status,
        package_name: item.contract_package,
        months: item.contract_months,
        total_amount: item.total_amount,
        full_name: item.full_name,
        trainer_name: item.trainer_name,
        signature_data: item.signature_data,
        slot_hold_expire_at: item.slot_hold_expire_at,
        membership_qr_token: item.membership_qr_token,
        member_id: item.member_id,
      } : {};
      this.signature = item.signature_data || item.full_name || '';
      this.paymentFailed = item.latest_payment_status === 'FAILED';
      this.paid = item.contract_status === 'PAID' || item.status === 'COMPLETED';
      this.invoiceNumber = item.invoice_number || '';
      this.cancelled = ['CANCELLED', 'NOT_SIGNED', 'EXPIRED', 'LEAD_SAVED'].includes(item.status);
      if (this.currentTask === 'T1') this.step = 1;
      else if (['TV', 'TD'].includes(this.currentTask) && item.package_name) this.step = 3;
      else if (['T5', 'T6', 'TV', 'TD'].includes(this.currentTask)) this.step = 2;
      else if (['TS', 'TQ', 'TA', 'TM'].includes(this.currentTask)) this.step = 3;
      else if (['TP', 'TC', 'TSG', 'E1', 'E2', 'ESe'].includes(this.currentTask)) this.step = 4;
      else if (['TPAY', 'E3'].includes(this.currentTask)) this.step = 5;
      if (this.role === 'customer' && ['TS', 'TQ'].includes(this.currentTask) && !item.slot_id) {
        const result = await this.api('/api/matching/find-trainers', { method: 'POST', body: JSON.stringify({ survey_id: item.survey_id }) });
        this.trainerCandidates = result.matched_trainers || [];
        this.currentTask = result.next_task;
        this.done = [...new Set([...this.done, 'TS'])];
        if (this.process) { this.process.current_task = result.next_task; this.process.completed_tasks = JSON.stringify(this.done); }
      } else if (this.currentTask !== 'TQ') this.trainerCandidates = [];
      if (this.role === 'customer' && this.step === 3 && this.survey) {
        this.packages = await this.api('/api/packages');
        this.quote = await this.api('/api/pricing/calculate', {
          method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id, goal: this.survey.predicted_goal, package_name: this.packageName, months: this.months }),
        });
      }
    },
    async refreshRole() {
      if (this.role === 'customer') {
        try { await this.loadQuestions(); } catch { /* role may not have survey access */ }
        await this.refreshProcess();
      }
      if (this.role === 'consultant') {
        const lists = await Promise.all([
          this.api('/api/consultant/pending-reviews'),
          this.api('/api/consultant/pending-consults'),
        ]);
        this.pending = lists[0];
        this.pendingConsults = lists[1];
        this.review = null;
        const nextItem = this.pending[0] || this.pendingConsults[0];
        if (nextItem) {
          this.process = nextItem; this.currentTask = this.pending.length ? 'T5' : 'TD';
          try { this.done = JSON.parse(this.process.completed_tasks || '[]'); } catch { this.done = []; }
        }
      }
      if (this.role === 'manager') {
        const results = await Promise.all([
          this.api('/api/manager/unassigned-slots'),
          this.api('/api/trainers'),
        ]);
        this.unassigned = results[0];
        this.allTrainers = results[1];
        if (this.unassigned.length) {
          this.process = this.unassigned[0]; this.currentTask = 'TM';
          try { this.done = JSON.parse(this.process.completed_tasks || '[]'); } catch { this.done = []; }
        }
      }
      if (this.role === 'pt') {
        this.schedule = await this.api('/api/pt/schedule');
        const slotProcess = this.schedule.find((item) => item.schedule_status === 'WAITING_PT') || this.schedule[0];
        if (slotProcess) {
          this.process = slotProcess; this.currentTask = slotProcess.current_task || 'TP';
          try { this.done = JSON.parse(this.process.completed_tasks || '[]'); } catch { this.done = []; }
        }
      }
      if (this.role === 'admin') {
        this.overview = await this.api('/api/admin/overview');
        this.overview.packages.forEach((item) => { this.packagePrices[item.id] = item.monthly_price; });
      }
    },
    async submitSurvey() {
      return this.busy(async () => {
        const result = await this.api('/api/survey/submit', { method: 'POST', body: JSON.stringify(this.form) });
        this.step = 2;
        await this.refreshProcess();
        this.notify(result.next_task === 'T5' ? 'Hồ sơ đã lưu; Tư vấn viên cần xác nhận mục tiêu tại T5.' : 'Đã hoàn tất T1–T4. Tiếp theo là T6 lập báo giá.');
      });
    },
    async openPackages() {
      return this.busy(async () => {
        this.packages = await this.api('/api/packages');
        this.quote = await this.api('/api/pricing/calculate', {
          method: 'POST',
          body: JSON.stringify({ survey_id: this.survey.survey_id, goal: this.survey.predicted_goal, package_name: this.packageName, months: this.months }),
        });
        this.currentTask = 'TV';
        await this.refreshProcess();
        this.step = 3;
      });
    },
    async loadQuote() {
      if (!this.survey) return;
      return this.busy(async () => {
        if (!this.packages.length) this.packages = await this.api('/api/packages');
        this.quote = await this.api('/api/pricing/calculate', {
          method: 'POST',
          body: JSON.stringify({ survey_id: this.survey.survey_id, goal: this.survey.predicted_goal, package_name: this.packageName, months: this.months }),
        });
      });
    },
    async confirmPackage() {
      return this.busy(async () => {
        const choice = await this.api('/api/packages/select', {
          method: 'POST',
          body: JSON.stringify({ survey_id: this.survey.survey_id, package_name: this.packageName, months: this.months }),
        });
        this.quote = choice.quote;
        if (choice.includes_pt) {
          const matches = await this.api('/api/matching/find-trainers', {
            method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id }),
          });
          this.trainerCandidates = matches.matched_trainers || [];
          await this.refreshProcess();
          if (!this.trainerCandidates.length) this.notify(matches.next_task === 'TM' ? 'Đã chuyển hồ sơ đến Quản lý PT tại TM.' : 'Chưa có PT đạt ngưỡng và còn ca; chuyển sang TA.');
          else this.notify('Chọn PT và một ca còn trống. Ca sẽ được giữ 48 giờ để PT xác nhận.');
        } else {
          this.contract = await this.api('/api/contracts/generate', {
            method: 'POST',
            body: JSON.stringify({ survey_id: this.survey.survey_id, trainer_id: null, package_name: this.packageName, months: this.months }),
          });
          this.step = 4;
          await this.refreshProcess();
          this.notify('TX đã ghi nhận gói không PT; hợp đồng TC đã được tạo.');
        }
      });
    },
    async deepConsult() {
      const details = window.prompt('Bạn muốn trao đổi thêm nội dung gì với tư vấn viên?');
      if (!details) return;
      return this.busy(async () => {
        await this.api('/api/consultant/deep-consult', {
          method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id, details }),
        });
        await this.refreshProcess();
        this.step = 3;
        this.notify('Đã gửi yêu cầu G2; hồ sơ đang chờ Tư vấn viên hoàn tất Task TD.');
      });
    },
    async completeConsult(row) {
      return this.busy(async () => {
        const response = this.consultantResponses[row.survey_id] || '';
        if (response.trim().length < 2) throw new Error('Nhập nội dung tư vấn trước khi hoàn tất TD.');
        await this.api('/api/consultant/complete-consult', {
          method: 'POST', body: JSON.stringify({ survey_id: row.survey_id, response }),
        });
        this.pendingConsults = await this.api('/api/consultant/pending-consults');
        if (this.process?.survey_id === row.survey_id) {
          this.currentTask = 'TV'; this.done = [...new Set([...this.done, 'TD'])];
        }
        this.notify(`Đã hoàn tất tư vấn TD cho hồ sơ #${row.survey_id}; khách quay lại TV.`);
      });
    },
    async showAlternatives() {
      return this.busy(async () => {
        const result = await this.api('/api/matching/alternative-slots', {
          method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id }),
        });
        this.trainerCandidates = result.alternatives || [];
        await this.refreshProcess();
        if (result.next_task === 'TM') this.notify('Đã đủ 3 lần thử; hồ sơ chuyển sang Quản lý PT tại TM.');
        else if (this.trainerCandidates.length) this.notify(`TA đã đề xuất phương án; còn ${result.attempts_remaining} lần thử.`);
        else this.notify('Chưa có PT hoặc ca thay thế trống. Bạn có thể làm mới hoặc chờ quản lý xử lý.');
      });
    },
    async holdSlot(trainer, slot) {
      return this.busy(async () => {
        await this.api('/api/slots/hold', {
          method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id, trainer_id: trainer.trainer_id, slot_id: slot.slot_id }),
        });
        this.step = 4;
        this.trainerCandidates = [];
        await this.refreshProcess();
        this.notify('TQ đã giữ ca 48 giờ; đang chờ PT xác nhận tại TP.');
      });
    },
    async declineOffer() {
      return this.busy(async () => {
        await this.api('/api/leads/save-drop', {
          method: 'POST', body: JSON.stringify({ survey_id: this.survey.survey_id, reason: 'Khách từ chối gói tại nhánh G3' }),
        });
        await this.refreshProcess();
        this.step = 4;
        this.notify('G3 chuyển nhánh từ chối; TL đã lưu hồ sơ tiềm năng.');
      });
    },
    async signContract() {
      if (!this.agree) return this.notify('Vui lòng đồng ý với điều khoản dịch vụ.');
      if (!this.signature.trim()) return this.notify('Nhập chữ ký điện tử hoặc OTP demo.');
      return this.busy(async () => {
        await this.api(`/api/contracts/${this.contract.contract_id}/sign`, {
          method: 'POST', body: JSON.stringify({ signature_data: this.signature }),
        });
        await this.refreshProcess();
        this.step = 5;
        this.notify('TSG hoàn tất; tiếp theo là thanh toán TPAY.');
      });
    },
    async declineContract() {
      return this.busy(async () => {
        await this.api(`/api/contracts/${this.contract.contract_id}/decline`, { method: 'POST' });
        await this.refreshProcess();
        this.step = 4;
        this.notify('GD: Không ký. Lịch PT được giải phóng nếu có; quy trình kết thúc tại E2.');
      });
    },
    async cancelProcess() {
      if (!window.confirm('Bạn xác nhận hủy đăng ký? Lịch PT sẽ được giải phóng nếu có.')) return;
      return this.busy(async () => {
        await this.api('/api/cancellation/process', {
          method: 'POST',
          body: JSON.stringify({ survey_id: this.survey?.survey_id, contract_id: this.contract.contract_id || null, reason: 'Khách hàng yêu cầu hủy đăng ký' }),
        });
        await this.refreshProcess();
        this.step = 4;
        this.notify('ESP hoàn tất: ES1 giải phóng lịch, ES2 lưu lý do hủy.');
      });
    },
    async remindContract() {
      return this.busy(async () => {
        await this.api(`/api/notifications/remind-contract?contract_id=${this.contract.contract_id}`, { method: 'POST' });
        await this.refreshProcess();
        this.notify('TNR đã ghi nhận. Hệ thống cũng tự nhắc sau 24 giờ nếu hợp đồng chưa ký.');
      });
    },
    async retryLink() {
      return this.busy(async () => {
        const result = await this.api(`/api/payments/retry-link?contract_id=${this.contract.contract_id}`, { method: 'POST' });
        await this.refreshProcess();
        this.notify(`TRP đã tạo liên kết thanh toán lại: ${result.retry_link}`);
      });
    },
    async doCheckout(simulateFailure) {
      return this.busy(async () => {
        const payment = await this.api('/api/payments/checkout', {
          method: 'POST',
          body: JSON.stringify({ contract_id: this.contract.contract_id, payment_method: this.payMethod, simulate_failure: simulateFailure }),
        });
        const verified = await this.api('/api/payments/webhook-verify', {
          method: 'POST', body: JSON.stringify({ transaction_ref: payment.transaction_ref, success: !simulateFailure }),
        });
        if (simulateFailure) {
          this.paymentFailed = true;
          await this.refreshProcess();
          this.step = 5;
          this.notify('TVF ghi nhận lỗi → TRP gửi link → quay lại TPAY. Hợp đồng vẫn đã ký.');
          return;
        }
        this.contract = { ...this.contract, ...verified.contract };
        this.invoiceNumber = verified.invoice_number;
        this.paid = true;
        this.paymentFailed = false;
        await this.refreshProcess();
        this.step = 5;
        this.notify('TVF thành công → TCD kích hoạt thẻ → TI xuất hóa đơn.');
      });
    },
    async resetDemo() {
      this.step = 1; this.process = null; this.survey = null; this.contract = {}; this.currentTask = 'T1'; this.done = [];
      this.trainerCandidates = []; this.cancelled = false; this.paid = false; this.paymentFailed = false;
      this.signature = ''; this.agree = false; this.invoiceNumber = '';
      this.form = { full_name: '', phone: '', email: '', date_of_birth: '', gender: '', raw_goal_text: '', coaching_style: 'MOTIVATIONAL', parq_answers: Array(7).fill(false) };
      this.notify('Sẵn sàng tạo hồ sơ mới.');
    },
    loadSample() {
      this.form = {
        full_name: 'Nguyễn Minh Anh', phone: '0901234567', email: 'minhanh.demo@example.com', date_of_birth: '1999-08-15', gender: 'FEMALE',
        raw_goal_text: 'Tôi muốn giảm cân, giảm mỡ bụng và eo thon trong 3 tháng.', coaching_style: 'MOTIVATIONAL', parq_answers: Array(7).fill(false),
      };
      this.notify('Đã điền dữ liệu mẫu. Nhấn Phân tích & tiếp tục.');
    },
    async verifyReview() {
      return this.busy(async () => {
        await this.api(`/api/consultant/verify-goal/${this.review.survey_id}`, {
          method: 'PUT', body: JSON.stringify({ goal: this.verifyGoal, notes: this.reviewNotes }),
        });
        this.pending = await this.api('/api/consultant/pending-reviews');
        const id = this.review.survey_id;
        this.review = null; this.reviewNotes = '';
        this.currentTask = 'T6';
        this.done = [...new Set([...this.done, 'T5'])];
        if (this.process) { this.process.current_task = 'T6'; this.process.completed_tasks = JSON.stringify(this.done); }
        this.notify(`T5 đã xác nhận hồ sơ #${id}; tiến trình được lưu để khách tiếp tục tại T6.`);
      });
    },
    async loadManagerSlots(row) {
      if (!this.assignments[row.survey_id]) { this.managerSlots[row.survey_id] = []; return; }
      return this.busy(async () => {
        const options = await this.api(`/api/trainers/slots?trainer_id=${this.assignments[row.survey_id]}`);
        this.managerSlots[row.survey_id] = options;
        this.selectedSlots[row.survey_id] = options[0]?.slot_id || null;
      });
    },
    async assignManual(row) {
      return this.busy(async () => {
        const trainerId = this.assignments[row.survey_id];
        const slotId = this.selectedSlots[row.survey_id];
        if (!trainerId || !slotId) throw new Error('Chọn PT và ca trống trước khi phân bổ.');
        await this.api('/api/manager/assign-trainer', {
          method: 'PUT', body: JSON.stringify({ survey_id: row.survey_id, trainer_id: trainerId, slot_id: slotId }),
        });
        this.currentTask = 'TP'; this.done = [...new Set([...this.done, 'TM', 'TQ'])];
        await this.refreshRole();
        this.notify('TM đã phân bổ PT/ca; tiến trình chuyển sang TQ và chờ PT xác nhận tại TP.');
      });
    },
    async closeUnassigned(row) {
      return this.busy(async () => {
        await this.api('/api/manager/close-unassigned', {
          method: 'POST', body: JSON.stringify({ survey_id: row.survey_id, reason: 'Quản lý không thể bố trí PT phù hợp' }),
        });
        await this.refreshRole();
        this.notify('G_TM: Không bố trí được; TL đã lưu hồ sơ tiềm năng.');
      });
    },
    async respondSchedule(row, accepted) {
      return this.busy(async () => {
        const result = await this.api('/api/pt/respond-schedule', {
          method: 'POST', body: JSON.stringify({ survey_id: row.survey_id, accepted, note: this.ptNotes[row.survey_id] || '' }),
        });
        await this.refreshRole();
        this.notify(result.message);
      });
    },
    async savePackage(item) {
      return this.busy(async () => {
        const result = await this.api(`/api/admin/packages/${item.id}`, {
          method: 'PUT', body: JSON.stringify({ monthly_price: this.packagePrices[item.id], benefits: item.benefits }),
        });
        item.monthly_price = result.package.monthly_price;
        this.notify(`Đã cập nhật giá ${item.name}.`);
      });
    },
    async toggleTrainer(trainer) {
      return this.busy(async () => {
        await this.api(`/api/admin/trainers/${trainer.trainer_id}`, {
          method: 'PUT', body: JSON.stringify({ is_available: !trainer.is_available, tier: trainer.tier }),
        });
        trainer.is_available = !trainer.is_available;
        this.notify('Đã cập nhật trạng thái PT.');
      });
    },
    async releaseExpiredSlots() {
      return this.busy(async () => {
        const result = await this.api('/api/slots/release-expired', { method: 'POST' });
        this.notify(result.released ? `Đã giải phóng ${result.released} ca hết hạn.` : 'Không có ca giữ chỗ nào hết hạn.');
      });
    },
    taskClass(id) {
      if (this.done.includes(id)) return 'complete';
      if (this.currentTask === id) return 'active';
      return '';
    },
  },
});

window.activeLifeVm = window.activeLifeApp.mount('#app');
