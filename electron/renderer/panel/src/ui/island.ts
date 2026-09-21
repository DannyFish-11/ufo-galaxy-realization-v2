/**
 * 右上那块岛:感知与设备。
 *
 * 它是**同一个元素自己长大**,不是弹出来一个新浮层 —— 宽、高、圆角连续
 * 过渡,内容交叉淡入。弹出会让人觉得来了个新东西,而它其实一直在那儿。
 *
 * 状态**不用点**,用**深度**:在线的浮起来(柔影 + 顶边受光),降级的几乎
 * 贴平,离线的沉进表面(只剩凹槽,没有影子)。状态就是它离墙多远。
 *
 * 活跃**不用闪**,用**光的行走**:一道细光斜掠而过,忙就掠得频繁、闲就
 * 几秒才飘一次。这是 Weiser 与 Brown 那根 Dangling String 的做法 ——
 * 屏幕上的符号需要解读,而这种东西跟人的周边视觉阻抗匹配得更好:
 * 忙不忙是**余光里感觉到**的,不是读出来的。
 *
 * 收起态那枚药丸里装的是**一座微缩星系**(见 galaxy.ts)。它只讲一件事:
 * **还有多少东西连着** —— 连接浓度就是整座星系的明暗,每一台连着的设备是星海
 * 里一颗明显更亮的星。除此之外那枚药丸上什么都不放。
 *
 * 从前那儿是两排小方块(四条感知通路 + 几台设备)。方块得**数**,而数东西要用
 * 中央视觉;一片星海亮不亮是周边视觉直接给的,不经过「读」那一步。那几格方块
 * 讲的事一件没丢 —— 全在展开态里,一条不少地写着话。
 *
 */
import type { AmbientAction, DeviceRow, ModalityView, PerceptionView, TierView } from '../types';
import { LIT_CAPACITY, createGalaxy } from './galaxy';
import { POSE_WORD, createPet } from './pet';
import type { PetLive } from './pet';

/** 双模型档里那两位的中文名。后端给的是 perception / reasoning / both。 */
const ROLE_LABEL: Record<string, string> = {
  perception: '感知位',
  reasoning: '推理位',
  both: '一位全包',
};

const MODALITY_LABEL: Record<string, string> = {
  screen: '屏幕',
  camera: '摄像头',
  microphone: '麦克风',
  system_audio: '系统声',
};

/** 这一档对人的意思。**每一档都得说得出口**,否则五档等于没分。 */
function modalityNote(m: ModalityView): string {
  switch (m.state) {
    case 'live':
      return '在收';
    case 'idle':
      return m.signal_age_s === null ? '通着，还没来过信号' : `静了 ${Math.round(m.signal_age_s)} 秒`;
    case 'suppressed':
      return '它在说话，这拍不听自己';
    case 'paused':
      return '你按了暂停';
    case 'unavailable':
      return '这台机器没有这条通路';
    default:
      return '';
  }
}

/**
 * 展开态里的一行。
 *
 * **前面不放小方格。** 从前每行前面有一枚代表状态的小方块(离墙多远 = 什么状态),
 * 于是一行 36px、两行文字、左边还占 26px 的图标槽。四条感知加七台设备摆下来,
 * 整块岛就被撑满了,而它要说的事其实只有「谁是什么状态」。
 *
 * 现在照着系统设置面板那种排法:**名字在左,状态在右,一行说完**。方格撤了没有
 * 丢事实 —— 那枚方块讲的每一档本来就有一句话(在收 / 你按了暂停 / 这台机器没有
 * 这条通路……),话一直在右边写着,只是从前被挤到第二行去了。
 */
function unit(name: string, note: string, active: boolean, muted: boolean): HTMLElement {
  const row = document.createElement('span');
  row.className = 'unit';
  const n = document.createElement('span');
  n.className = 'unit-name';
  n.textContent = name;
  const s = document.createElement('span');
  s.className = 'unit-note';
  s.textContent = note;
  s.title = note;
  if (active) s.dataset['active'] = 'true';
  // 这一条不通 / 没有。**不是把整行调暗** —— 调暗了会被读成「不重要」,
  // 而「这台机器没有摄像头」恰恰是要看见的事实。只把状态那半边标出来。
  if (muted) row.dataset['off'] = 'true';
  row.append(n, s);
  return row;
}

export interface IslandHandles {
  readonly root: HTMLElement;
  render(
    perception: PerceptionView | null,
    devices: readonly DeviceRow[],
    tiers: TierView | null,
    privacyBusy: boolean,
    open: boolean,
    now: { phase: PetLive['phase']; activity: string },
  ): void;
  /** 展开后与左边卡片区顶对齐、等高。 */
  setHeight(px: number): void;
}

export interface IslandCallbacks {
  onToggle(): void;
  /** 按停 / 恢复桌面感知。**这是岛上唯一一个能按的东西** —— 见下方说明。 */
  onPrivacy(paused: boolean): void;
}

export function createIsland(cb: IslandCallbacks): IslandHandles {
  const island = document.createElement('button');
  island.className = 'island';
  island.type = 'button';
  island.setAttribute('aria-label', '感知与设备');

  const mini = document.createElement('span');
  mini.className = 'island-view island-mini';
  const galaxy = createGalaxy();
  mini.append(galaxy.root);

  const full = document.createElement('span');
  full.className = 'island-view island-full';
  const perKey = document.createElement('span');
  perKey.className = 'sec-key';
  const perCount = document.createElement('b');

  /**
   * 「别看了」。**岛上唯一一个能按的东西。**
   *
   * 破一次「岛是状态面不是控制面」的例,理由是这个动作与别的设置不同类:
   * 它要的是**此刻立刻生效**,而不是「改个配置等它生效」。要人先开设置浮层、
   * 再翻到感知那一栏、再找到某个键 —— 想遮住摄像头的那几秒里,这条路太长了。
   *
   * 它就摆在四条感知通路的正上方:要停的东西和停它的开关在同一处,不用回想
   * 「这个开关管的是哪几条」。
   */
  const privacy = document.createElement('button');
  privacy.className = 'privacy-btn';
  privacy.type = 'button';
  privacy.addEventListener('click', (e) => {
    // 岛自己那个「点哪儿都收起」的监听在外层。不拦住的话,按一下暂停顺手
    // 把岛关了 —— 而这一按恰恰是最需要看见结果的一按。
    e.stopPropagation();
    if (privacy.disabled) return;
    cb.onPrivacy(privacy.dataset['paused'] !== 'true');
  });

  perKey.append(document.createTextNode('感知'), privacy, perCount);
  const perGrid = document.createElement('span');
  perGrid.className = 'per-grid';
  const devKey = document.createElement('span');
  devKey.className = 'sec-key dev-key';
  const devCount = document.createElement('b');
  devKey.append(document.createTextNode('设备'), devCount);
  const devList = document.createElement('span');
  devList.className = 'dev-list';

  // 展开态最下面一行:此刻在跑哪一档、哪两个型号。**只读。**
  //
  // 换档在设置浮层那边(那里能看见一共有几档、哪几档这台机器跑不动)。这里只
  // 回答「现在是什么」—— 岛是状态面,不是控制面;把换档也塞进来的话,人会在
  // 余光里误触一次代价很大的操作(驱逐旧模型、拉新模型、热刷 LLM 路由)。
  const brainKey = document.createElement('span');
  brainKey.className = 'sec-key brain-key';
  const brainTier = document.createElement('b');
  brainKey.append(document.createTextNode('本机模型'), brainTier);
  const brainLine = document.createElement('span');
  brainLine.className = 'brain-line';

  // 展开之后把那一拍**说成话**。收起态只有一道光:光讲得出「往外还是往内」,
  // 讲不出「为什么」。后端把理由原文一起发来了(已截断到 200 字),这儿是它
  // 唯一放得下的地方。
  const wakeKey = document.createElement('span');
  wakeKey.className = 'sec-key brain-key';
  const wakeWord = document.createElement('b');
  wakeKey.append(document.createTextNode('自发注意力'), wakeWord);
  const wakeLine = document.createElement('span');
  wakeLine.className = 'brain-line';

  /**
   * 那只小东西坐在这一栏右边。
   *
   * 它跟左边那两行讲的是**同一件事**,不是另一份数据 —— 脸讲得快(眼睛闭没闭、
   * 身子探没探,不用读),字讲得准(为什么这么决定)。两边都从同一帧来,
   * 所以不会出现「脸上笑着而字写着已暂停」那种两处不一致。
   */
  const pet = createPet();
  const wakeWrap = document.createElement('span');
  wakeWrap.className = 'wake-wrap';
  const wakeText = document.createElement('span');
  wakeText.className = 'wake-text';
  wakeText.append(wakeKey, wakeLine);
  wakeWrap.append(wakeText, pet.root);

  full.append(perKey, perGrid, devKey, devList, brainKey, brainLine, wakeWrap);

  island.append(mini, full);

  // 展开之后点它任何一处都收回去。挡住内部点击的话就永远关不上 ——
  // 因为展开态整个内部就是那一层。
  //
  // stopPropagation 是必须的:document 上那个「点别处收起」的监听器会收到
  // 同一次冒泡上来的 click,于是刚展开就被自己关掉 —— 看起来是「点了没反应」。
  island.addEventListener('click', (e) => {
    e.stopPropagation();
    cb.onToggle();
  });

  function render(
    perception: PerceptionView | null,
    devices: readonly DeviceRow[],
    tiers: TierView | null,
    privacyBusy: boolean,
    open: boolean,
    /** 此刻这一帧的主轴与阈限内容 —— 那只小东西的底子靠这两位实时动起来。 */
    now: { phase: PetLive['phase']; activity: string },
  ): void {
    island.dataset['open'] = String(open);

    // **停没停这件事只有一个权威:posture 帧。**
    //
    // `perception.privacy_paused` 每一帧都带着。面板另外攒一份(启动时问一次
    // HTTP、点一下改一次)就是同一个事实两处各存 —— 别处按停之后帧里说停了、
    // 四条通路画成 paused,而按钮还写着「暂停感知」。这里直接读那一份。
    //
    // 三态,不是两态。`perception` 为 null = **还没收到过帧**:那时按钮不该说
    // 「正在采」,也不该说「已暂停」—— 说错任何一边都比说「不知道」糟。
    const paused = perception === null ? null : perception.privacy_paused;
    privacy.dataset['paused'] = String(paused === true);
    privacy.dataset['unknown'] = String(paused === null);
    privacy.disabled = paused === null || privacyBusy;
    privacy.textContent =
      paused === null ? '状态未知' : privacyBusy ? '…' : paused ? '已暂停 · 点恢复' : '暂停感知';
    privacy.title =
      paused === null
        ? '还没收到过感知帧 —— 停没停不知道'
        : paused
          ? '感知已停:屏幕/摄像头/麦克风/系统声都不再采,缓存已清空'
          : '立刻停止采集并清空缓存（环境循环、电脑操作、会话记忆、多模态注入同时失明）';
    privacy.setAttribute('aria-pressed', String(paused === true));
    island.setAttribute('aria-expanded', String(open));

    perGrid.replaceChildren();
    devList.replaceChildren();

    // 感知恒定四条。**缺的那条以 unavailable 出现,不是从队列里消失** ——
    // 遍历一个长度会变的数组,就永远画不出「这一侧没有」。
    const modalities = perception?.modalities ?? [];
    for (const m of modalities) {
      perGrid.append(
        unit(
          MODALITY_LABEL[m.modality] ?? m.modality,
          modalityNote(m),
          m.state === 'live',
          m.state === 'unavailable',
        ),
      );
    }
    const live = modalities.filter((m) => m.state === 'live').length;
    // 「四条都没在收」和「这条链路压根没建起来」是两件事。
    //
    // 后端如实报着 perception.source = 'unwired',而这行字原先只按数量算,
    // 于是两种情形写出来一模一样是 `0 / 4 在收` —— 看着像此刻恰好安静,其实是
    // 桌面壳一帧都没推过。契约特地分了这两个值,面板不能在最后一步把它抹平。
    const wired = perception !== null && perception.source === 'live';
    perCount.textContent = !modalities.length
      ? '未接'
      : wired
        ? `${live} / ${modalities.length} 在收`
        : `${modalities.length} 条 · 还没接上`;
    perKey.dataset['unwired'] = String(modalities.length > 0 && !wired);

    // 上一拍自发注意力决定了什么。**只在展开态写着** —— 收起态那枚药丸归星系,
    // 别的什么都不放。
    const act: AmbientAction | null = perception === null ? null : perception.ambient_action;
    const why = perception === null ? '' : perception.ambient_rationale;
    wakeWord.textContent = act === null ? '未接' : POSE_WORD[act] ?? '还没决策过';
    wakeKey.dataset['unwired'] = String(act === null);
    wakeLine.textContent =
      act === null
        ? '还没收到过感知帧 —— 上一拍决定了什么不知道'
        : why || (act === 'none' ? '这条会话里它还没自己动过念头' : '后端没给理由');
    wakeLine.title = wakeLine.textContent;
    // 理由是空串时那行写的是替代话,不是后端原文 —— 降级留痕。
    wakeLine.dataset['unwired'] = String(act === null || (act !== 'none' && !why));
    // 脸和话同一帧喂,两处不会讲岔。
    pet.render({
      phase: now.phase,
      activity: now.activity,
      // 「在不在收」有三态:还没收到过帧时是**不知道**,不是「没在收」。
      sensing: perception === null ? null : perception.is_sensing,
      paused,
      act,
    });

    // 星海只按名册亮暗,不在这里挑谁进得去 —— 挑法在 galaxy.ts,而且是定死的:
    // 第 n 台设备永远是同一颗星,掉线就是那一颗淡回去。
    galaxy.render(devices);

    for (const d of devices) {
      const note =
        d.state === 'offline'
          ? d.lastSeenS === null
            ? '离线 · 从没连上过'
            : `离线 · 上次 ${formatAgo(d.lastSeenS)}`
          : d.doing
            ? d.doing
            : d.load === null
              ? // 「在线」和「降级」是两档,写出来也得是两句 —— 一台降级的机器
                // 顶着「在线」两个字,那格沉下去的深度就白做了。
                `${d.state === 'degraded' ? '降级' : '在线'} · ${
                  d.lastSeenS === null ? '没报过在忙什么' : `${formatAgo(d.lastSeenS)}有心跳`
                }`
              : '空闲';
      devList.append(unit(d.name, note, d.load === 'busy', d.state === 'offline'));
    }
    const online = devices.filter((d) => d.state !== 'offline').length;
    devCount.textContent = devices.length ? `${online} / ${devices.length} 在线` : '未接';
    // 星海是给余光的;读屏软件读不出「这片亮了几颗」,所以同一件事也得说成话。
    // 药丸标了 aria-hidden 而标签里没有,这一整块对读屏就等于不存在。
    //
    // **设备多到星海排不下时必须留痕。** galaxy.ts 只挑得出 LIT_CAPACITY 颗
    // 互不粘连的星,再多就有设备没有自己的那一颗 —— 画面上看着是「就这么些」,
    // 而那正是这块面板最不许犯的那种错。眼睛这边没处放,至少这儿得说出来。
    const unplaced = Math.max(0, devices.length - LIT_CAPACITY);

    // **感知停没停,收起态必须说得出口。**
    //
    // 从前这枚药丸上有四格小方块,按了「别看了」那一格会沉下去 —— 停没停是
    // 余光可见的。改成星系之后那四格撤了,而星系讲的是**设备**,讲不了感知:
    // 于是急停生效时,收起态的药丸和平常长得一模一样。
    //
    // 这一位是这块面板上最不该悄悄消失的:人按下它,是因为此刻不想被看/被听。
    // 药丸上不再加东西(那是所有者定的),但至少这一层不能也是哑的 —— 读屏读
    // 得到,指针停上去看得到。**眼睛那一侧仍然是空的,那是一个还没补的洞。**
    // `paused` 是上面那一份 —— 停没停的唯一权威是 posture 帧,这里不另算一遍。
    const senseWord =
      paused === true
        ? '感知已暂停'
        : perception === null
          ? '还没收到过感知帧'
          : !wired && modalities.length > 0
            ? '感知还没接上'
            : '';

    island.setAttribute(
      'aria-label',
      [
        '感知与设备',
        senseWord,
        devices.length ? `${online} / ${devices.length} 台在线` : '',
        unplaced ? `星图放不下其中 ${unplaced} 台` : '',
        act === null ? '' : POSE_WORD[act] ?? '',
      ]
        .filter(Boolean)
        .join(' · '),
    );
    island.title = [
      senseWord,
      unplaced ? `星图只画得下 ${LIT_CAPACITY} 台，还有 ${unplaced} 台在展开态里` : '',
    ]
      .filter(Boolean)
      .join(' · ');

    // 本机模型那一行。**三种状态各写各的话**:
    //   null      —— 没拉到目录。不是「没有档位」,别写成空白。
    //   有 current —— 写出档位标签和两位实际在跑的型号。「C 档」三个字说不出
    //                在跑哪两个模型,而那才是人想确认的东西。
    //   current 空 —— 拉到了目录但一档都没选定。这也得说出来。
    if (tiers === null) {
      brainTier.textContent = '读不到';
      brainKey.dataset['unwired'] = 'true';
      brainLine.textContent = '拿不到档位目录 —— 后端没接上';
      brainLine.dataset['unwired'] = 'true';
      brainLine.title = '';
    } else {
      const cur = tiers.tiers.find((t) => t.key === tiers.current);
      const bad = !!cur && (cur.fit === 'no_gpu' || cur.fit === 'insufficient_vram');
      brainTier.textContent = cur
        ? `${cur.key} 档`
        : tiers.current
          ? `${tiers.current} 档?`
          : '未选定';
      brainKey.dataset['unwired'] = String(!cur || bad);

      // 型号名一行摆完,摆不下就省略 —— 全称在 title 里,也在设置浮层那一行里
      // 完整写着。**岛是余光扫一眼的地方**,不该为两个型号 id 吃掉设备列表三分之一
      // 的高度(它先前正是这么干的:设备列表从 123px 缩到 73px,四台只露两台)。
      const slots = tiers.slots.filter((x) => x.model).map((x) => `${ROLE_LABEL[x.role] ?? x.role} ${x.model}`);
      const detail = cur
        ? slots.length
          ? slots.join(' · ')
          : cur.label
        : tiers.current
          ? '目录里没有这一档'
          : '还没选定档位';
      // 装不下也要说 —— 岛上写着「C 档」而这台机器跑不动 C,是最难查的那种误导。
      brainLine.textContent = bad ? `${cur!.fitReason} · ${detail}` : detail;
      brainLine.title = detail;
      brainLine.dataset['unwired'] = String(!cur || bad);
    }
  }

  function setHeight(px: number): void {
    if (px > 60) island.style.setProperty('--island-h', `${px}px`);
  }

  return { root: island, render, setHeight };
}

function formatAgo(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} 秒前`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} 分钟前`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} 小时前`;
  return `${Math.round(seconds / 86400)} 天前`;
}
