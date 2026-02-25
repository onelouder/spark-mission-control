import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createRoot } from 'react-dom/client';

// --- Types ---

type Status = 'working' | 'inactive' | 'waiting';

interface ChatAgent {
  id: number;
  name: string;
  role: string;
  status: Status;
  lastMessage: string;
  history: string[];
}

interface KanbanCard {
  id: string;
  title: string;
  tag: string;
  assignee: string;
}

interface KanbanColumn {
  id: string;
  title: string;
  cards: KanbanCard[];
}

// --- Mock Data ---

const INITIAL_AGENTS: ChatAgent[] = Array.from({ length: 10 }).map((_, i) => ({
  id: i + 1,
  name: `AGENT-${(i + 1).toString().padStart(2, '0')}`,
  role: i % 3 === 0 ? 'RESEARCH' : i % 3 === 1 ? 'CODER' : 'REVIEWER',
  status: i === 9 ? 'working' : i % 4 === 0 ? 'waiting' : 'inactive',
  lastMessage: i === 9 ? 'Synthesizing final architectural decision records...' : 'Waiting for input context from upstream...',
  history: [
    `[SYSTEM]: Agent initialized.`,
    `[LOG]: Loaded local context from vector store.`,
    `[THOUGHT]: Analyzing request for sovereignty compliance.`,
    `[OUTPUT]: Ready to process task #${1000 + i}.`,
    ...(i === 9 ? [`[ACTION]: Running local inference on Llama-3...`, `[UPDATE]: 45% complete.`] : [])
  ]
}));

const INITIAL_KANBAN: KanbanColumn[] = [
  {
    id: 'todo',
    title: 'BACKLOG',
    cards: [
      { id: 'T-101', title: 'Integrate Ollama local endpoints', tag: 'INFRA', assignee: 'DevOps' },
      { id: 'T-102', title: 'Refactor vector store schema', tag: 'DB', assignee: 'Alice' },
      { id: 'T-103', title: 'Implement MCP tool bridge', tag: 'AGENT', assignee: 'Bob' },
      { id: 'T-104', title: 'Audit privacy leakage in logs', tag: 'SEC', assignee: 'SecTeam' },
    ]
  },
  {
    id: 'progress',
    title: 'IN PROGRESS',
    cards: [
      { id: 'T-099', title: 'Dashboard UI Development', tag: 'FRONT', assignee: 'Alice' },
      { id: 'T-098', title: 'PostgreSQL Docker container setup', tag: 'OPS', assignee: 'DevOps' },
      { id: 'T-097', title: 'Optimize Context Window', tag: 'AI', assignee: 'Bob' },
    ]
  },
  {
    id: 'done',
    title: 'DONE',
    cards: [
      { id: 'T-050', title: 'Initial repo setup', tag: 'META', assignee: 'Alice' },
      { id: 'T-051', title: 'Select embedding model', tag: 'AI', assignee: 'Bob' },
      { id: 'T-052', title: 'Configure TypeScript linting', tag: 'DX', assignee: 'Alice' },
    ]
  }
];

// --- Hooks ---

/**
 * Skeleton hook for AI Agent Runtime.
 * TODO: Replace the mock timeout with actual calls to Ollama/LocalAI.
 */
const useAgentRuntime = (initialAgents: ChatAgent[]) => {
  const [agents, setAgents] = useState<ChatAgent[]>(initialAgents);
  // Track which agent is currently "thinking"
  const [processingId, setProcessingId] = useState<number | null>(null);

  const sendMessage = async (agentId: number, userMessage: string) => {
    // 1. Optimistic Update: Show user message immediately
    setAgents(prev => prev.map(a => {
      if (a.id === agentId) {
        return {
          ...a,
          lastMessage: userMessage, // Update preview
          history: [...a.history, `[USER]: ${userMessage}`],
          status: 'working'
        };
      }
      return a;
    }));

    setProcessingId(agentId);

    // 2. AI Inference Skeleton
    try {
      // --- SKELETON START: Replace this block with your local inference call ---
      
      // const response = await fetch('http://localhost:11434/api/generate', {
      //   method: 'POST',
      //   body: JSON.stringify({ model: 'llama3', prompt: userMessage })
      // });
      // const data = await response.json();
      
      await new Promise(resolve => setTimeout(resolve, 1200)); // Mock latency
      const mockResponse = `[OUTPUT]: I have received command "${userMessage}". Executing step 1 of 3...`;
      
      // --- SKELETON END ---

      // 3. Update with AI Response
      setAgents(prev => prev.map(a => {
        if (a.id === agentId) {
          return {
            ...a,
            lastMessage: "Command executed.",
            history: [...a.history, mockResponse],
            status: 'waiting' // or 'inactive' depending on logic
          };
        }
        return a;
      }));

    } catch (error) {
      console.error("Agent Error:", error);
      setAgents(prev => prev.map(a => {
        if (a.id === agentId) {
          return { ...a, status: 'inactive', lastMessage: 'Error during inference.' };
        }
        return a;
      }));
    } finally {
      setProcessingId(null);
    }
  };

  return { agents, sendMessage, processingId };
};

// --- Components ---

const StatusLight = ({ status }: { status: Status }) => {
  const color = status === 'working' ? 'var(--status-working)' 
              : status === 'waiting' ? 'var(--status-waiting)' 
              : 'var(--status-inactive)';
  
  const isWorking = status === 'working';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: '12px',
      height: '12px',
      marginRight: '8px'
    }}>
      <div 
        className={isWorking ? 'status-pulse' : ''}
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: isWorking ? `0 0 5px ${color}` : 'none'
        }} 
      />
    </div>
  );
};

const Header = () => (
  <header style={{
    height: '32px',
    backgroundColor: 'var(--bg0)',
    borderBottom: '1px solid var(--border0)',
    display: 'flex',
    alignItems: 'center',
    padding: '0 12px',
    fontSize: '11px',
    justifyContent: 'space-between',
    userSelect: 'none',
    flexShrink: 0
  }}>
    <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
      <div className="mono" style={{ fontWeight: 700, color: 'var(--text0)', letterSpacing: '0.5px' }}>Agent Work Queue</div>
      <nav style={{ display: 'flex', gap: '16px' }}>
        {['File', 'Edit', 'View', 'Terminal', 'Help'].map(item => (
          <span key={item} style={{ cursor: 'pointer', color: 'var(--text1)', transition: 'color 75ms' }} 
                onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text0)'}
                onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text1)'}>
            {item}
          </span>
        ))}
      </nav>
    </div>
    <div className="mono" style={{ fontSize: '10px', color: 'var(--text2)', display: 'flex', gap: '12px' }}>
      <span style={{color: 'var(--success)'}}>● LOCAL: ONLINE</span>
      <span>GPU: 24%</span>
      <span>MEM: 4.2GB</span>
    </div>
  </header>
);

// --- Kanban Components ---

interface KanbanCardProps {
  card: KanbanCard;
  columnId: string;
  onDelete: (id: string) => void;
  onUpdate: (id: string, newTitle: string) => void;
  onDragStart: (e: React.DragEvent, cardId: string, columnId: string) => void;
  onDropOnCard: (e: React.DragEvent, targetCardId: string, targetColumnId: string) => void;
  onAnalyze: (card: KanbanCard) => void;
}

const KanbanCardComponent = ({ card, columnId, onDelete, onUpdate, onDragStart, onDropOnCard, onAnalyze }: KanbanCardProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(card.title);
  const [isHovered, setIsHovered] = useState(false);

  const handleSave = () => {
    if (editValue.trim()) {
      onUpdate(card.id, editValue);
    } else {
      setEditValue(card.title); // revert if empty
    }
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') {
      setEditValue(card.title);
      setIsEditing(false);
    }
  };

  return (
    <div 
      draggable={!isEditing}
      onDragStart={(e) => onDragStart(e, card.id, columnId)}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onDropOnCard(e, card.id, columnId);
      }}
      style={{
        backgroundColor: 'var(--bg2)',
        border: '1px solid var(--border1)',
        borderRadius: '2px',
        padding: '8px 10px',
        cursor: isEditing ? 'text' : 'grab',
        transition: 'background-color 75ms, border-color 75ms',
        position: 'relative',
      }}
      onMouseEnter={(e) => {
        if (!isEditing) {
          e.currentTarget.style.backgroundColor = 'var(--bg3)';
          e.currentTarget.style.borderColor = 'var(--border2)';
          setIsHovered(true);
        }
      }}
      onMouseLeave={(e) => {
        if (!isEditing) {
          e.currentTarget.style.backgroundColor = 'var(--bg2)';
          e.currentTarget.style.borderColor = 'var(--border1)';
          setIsHovered(false);
        }
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', alignItems: 'center' }}>
        <span className="mono" style={{ color: 'var(--accent)', fontSize: '10px', opacity: 0.8 }}>{card.id}</span>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <span style={{ 
            fontSize: '9px', 
            padding: '2px 4px', 
            backgroundColor: 'rgba(255,255,255,0.05)', 
            borderRadius: '2px',
            color: 'var(--text2)',
            fontWeight: 600,
            letterSpacing: '0.5px'
          }}>{card.tag}</span>
          <span style={{ 
            fontSize: '9px', 
            padding: '2px 4px', 
            backgroundColor: 'rgba(78, 161, 255, 0.1)', 
            borderRadius: '2px',
            color: 'var(--info)',
            fontWeight: 600,
            letterSpacing: '0.5px'
          }}>{card.assignee.slice(0, 2).toUpperCase()}</span>
        </div>
      </div>
      
      {isEditing ? (
        <input 
          autoFocus
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          style={{
            width: '100%',
            background: 'var(--bg0)',
            border: '1px solid var(--accent)',
            color: 'var(--text0)',
            fontSize: '11px',
            padding: '4px',
            outline: 'none',
            fontFamily: 'inherit'
          }}
        />
      ) : (
        <div style={{ lineHeight: '1.4', fontSize: '11px', color: 'var(--text0)', wordWrap: 'break-word' }}>
          {card.title}
        </div>
      )}

      {/* Hover Actions */}
      {isHovered && !isEditing && (
        <div style={{
          position: 'absolute',
          top: '2px',
          right: '2px',
          display: 'flex',
          gap: '2px',
          backgroundColor: 'var(--bg2)',
          padding: '2px',
          borderRadius: '2px'
        }}>
           <button 
            onClick={(e) => { e.stopPropagation(); onAnalyze(card); }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--purple)',
              cursor: 'pointer',
              padding: '2px',
              fontSize: '10px'
            }}
            title="Analyze with AI Agent"
          >
            🤖
          </button>
          <button 
            onClick={() => setIsEditing(true)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text1)',
              cursor: 'pointer',
              padding: '2px',
              fontSize: '10px'
            }}
            title="Edit"
          >
            ✎
          </button>
          <button 
            onClick={() => {
              if (window.confirm('Delete this task?')) {
                onDelete(card.id);
              }
            }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--danger)',
              cursor: 'pointer',
              padding: '2px',
              fontSize: '10px'
            }}
            title="Delete"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
};

interface KanbanColumnProps {
  column: KanbanColumn;
  onAddCard: (columnId: string, title: string) => void;
  onDeleteCard: (columnId: string, cardId: string) => void;
  onUpdateCard: (columnId: string, cardId: string, newTitle: string) => void;
  onMoveCard: (draggedId: string, sourceColId: string, targetColId: string, targetIndex?: number) => void;
  onAnalyzeCard: (card: KanbanCard) => void;
}

const KanbanColumnComponent = ({ column, onAddCard, onDeleteCard, onUpdateCard, onMoveCard, onAnalyzeCard }: KanbanColumnProps) => {
  const [filterTag, setFilterTag] = useState<string>('All');
  const [filterAssignee, setFilterAssignee] = useState<string>('All');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | 'none'>('none');
  const [isAdding, setIsAdding] = useState(false);
  const [newCardTitle, setNewCardTitle] = useState('');

  // Derive unique options
  const tags = useMemo(() => ['All', ...new Set(column.cards.map(c => c.tag))], [column.cards]);
  const assignees = useMemo(() => ['All', ...new Set(column.cards.map(c => c.assignee))], [column.cards]);

  // Filter and Sort
  const processedCards = useMemo(() => {
    let result = [...column.cards];

    if (filterTag !== 'All') {
      result = result.filter(c => c.tag === filterTag);
    }
    if (filterAssignee !== 'All') {
      result = result.filter(c => c.assignee === filterAssignee);
    }

    if (sortOrder !== 'none') {
      result.sort((a, b) => {
        return sortOrder === 'asc' 
          ? a.title.localeCompare(b.title)
          : b.title.localeCompare(a.title);
      });
    }

    return result;
  }, [column.cards, filterTag, filterAssignee, sortOrder]);

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newCardTitle.trim()) {
      onAddCard(column.id, newCardTitle);
      setNewCardTitle('');
      setIsAdding(false);
    }
  };

  const handleDragStart = (e: React.DragEvent, cardId: string, colId: string) => {
    e.dataTransfer.setData('application/json', JSON.stringify({ cardId, colId }));
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDropOnColumn = (e: React.DragEvent) => {
    e.preventDefault();
    const data = e.dataTransfer.getData('application/json');
    if (!data) return;
    const { cardId, colId } = JSON.parse(data);
    // If dropped on column but not on specific card, append to end
    onMoveCard(cardId, colId, column.id); 
  };

  const handleDropOnCard = (e: React.DragEvent, targetCardId: string, targetColId: string) => {
    e.stopPropagation(); // Prevent column drop
    const data = e.dataTransfer.getData('application/json');
    if (!data) return;
    const { cardId, colId } = JSON.parse(data);
    
    // Find index of target card
    const targetIndex = column.cards.findIndex(c => c.id === targetCardId);
    onMoveCard(cardId, colId, targetColId, targetIndex);
  };

  const selectStyle: React.CSSProperties = {
    backgroundColor: 'var(--bg0)',
    color: 'var(--text1)',
    border: '1px solid var(--border1)',
    fontSize: '9px',
    padding: '2px 4px',
    borderRadius: '2px',
    outline: 'none',
    width: '100%',
    cursor: 'pointer'
  };

  return (
    <div 
      style={{
        flex: 1,
        minWidth: '220px',
        backgroundColor: 'var(--bg1)',
        display: 'flex',
        flexDirection: 'column',
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDropOnColumn}
    >
      {/* Controls Area */}
      <div style={{
        padding: '8px 12px 4px 12px',
        borderBottom: '1px solid var(--border0)',
        backgroundColor: 'var(--bg1)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '8px',
          fontSize: '10px',
          fontWeight: 700,
          color: 'var(--text1)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
        }}>
          <span>{column.title}</span>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ color: 'var(--text3)' }}>{processedCards.length}</span>
            <button 
              onClick={() => setIsAdding(!isAdding)}
              style={{
                background: 'var(--bg2)',
                border: '1px solid var(--border1)',
                color: 'var(--accent)',
                cursor: 'pointer',
                padding: '2px 6px',
                borderRadius: '2px',
                fontSize: '10px'
              }}
              title="Add Task"
            >
              +
            </button>
          </div>
        </div>

        {/* Filters Row */}
        <div style={{ display: 'flex', gap: '4px', marginBottom: '4px' }}>
          <select 
            value={sortOrder} 
            onChange={(e) => setSortOrder(e.target.value as any)}
            style={{ ...selectStyle, flex: 2 }}
          >
            <option value="none">Sort</option>
            <option value="asc">A-Z</option>
            <option value="desc">Z-A</option>
          </select>

          <select 
            value={filterTag} 
            onChange={(e) => setFilterTag(e.target.value)}
            style={{ ...selectStyle, flex: 3 }}
          >
            {tags.map(t => <option key={t} value={t}>{t === 'All' ? 'Tag' : t}</option>)}
          </select>

          <select 
            value={filterAssignee} 
            onChange={(e) => setFilterAssignee(e.target.value)}
            style={{ ...selectStyle, flex: 3 }}
          >
            {assignees.map(a => <option key={a} value={a}>{a === 'All' ? 'User' : a}</option>)}
          </select>
        </div>
        
        {/* Add Task Input */}
        {isAdding && (
          <form onSubmit={handleAddSubmit} style={{ marginTop: '4px' }}>
             <input 
                autoFocus
                placeholder="Task title..."
                value={newCardTitle}
                onChange={(e) => setNewCardTitle(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--bg0)',
                  border: '1px solid var(--accent)',
                  color: 'var(--text0)',
                  fontSize: '10px',
                  padding: '4px',
                  outline: 'none',
                  borderRadius: '2px'
                }}
             />
          </form>
        )}
      </div>

      {/* Cards List */}
      <div style={{ 
        padding: '12px', 
        overflowY: 'auto', 
        flex: 1, 
        display: 'flex', 
        flexDirection: 'column', 
        gap: '8px' 
      }}>
        {processedCards.map(card => (
          <KanbanCardComponent 
            key={card.id} 
            card={card} 
            columnId={column.id}
            onDelete={(id) => onDeleteCard(column.id, id)}
            onUpdate={(id, val) => onUpdateCard(column.id, id, val)}
            onDragStart={handleDragStart}
            onDropOnCard={handleDropOnCard}
            onAnalyze={onAnalyzeCard}
          />
        ))}
        {processedCards.length === 0 && !isAdding && (
          <div style={{ fontSize: '10px', color: 'var(--text3)', textAlign: 'center', marginTop: '12px' }}>
            Empty
          </div>
        )}
      </div>
    </div>
  );
};

interface ChatPaneProps {
  agents: ChatAgent[];
  openChatId: number;
  setOpenChatId: (id: number) => void;
  onSendMessage: (id: number, msg: string) => void;
}

const ChatPane = ({ agents, openChatId, setOpenChatId, onSendMessage }: ChatPaneProps) => {
  const scrollRefs = useRef<{[key: number]: HTMLDivElement | null}>({});
  const [inputVal, setInputVal] = useState('');

  const toggleChat = (id: number) => {
    setOpenChatId(id);
  };

  useEffect(() => {
    if (openChatId && scrollRefs.current[openChatId]) {
      const el = scrollRefs.current[openChatId];
      if (el) el.scrollTop = el.scrollHeight;
    }
  }, [openChatId, agents]); // Scroll on open or new message

  const handleSend = () => {
    if (inputVal.trim()) {
      onSendMessage(openChatId, inputVal.trim());
      setInputVal('');
    }
  };

  return (
    <div style={{
      flex: 1, 
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: 'var(--bg1)',
      overflow: 'hidden',
      height: '100%'
    }}>
      <div style={{
        height: '32px', // Match header height alignment
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        fontSize: '10px',
        fontWeight: 700,
        color: 'var(--text1)',
        borderBottom: '1px solid var(--border1)',
        textTransform: 'uppercase',
        letterSpacing: '1px',
        backgroundColor: 'var(--bg1)',
        flexShrink: 0
      }}>
        Active Threads ({agents.length})
      </div>
      
      <div style={{ 
        flex: 1, 
        display: 'flex', 
        flexDirection: 'column', 
        overflowY: 'hidden' 
      }}>
        {agents.map((agent) => {
          const isOpen = agent.id === openChatId;
          
          return (
            <div 
              key={agent.id}
              style={{
                display: 'flex',
                flexDirection: 'column',
                flex: isOpen ? '1 1 auto' : '0 0 auto',
                borderBottom: '1px solid var(--border0)',
                backgroundColor: isOpen ? 'var(--bg2)' : 'var(--bg1)',
                transition: 'flex-grow 0.1s ease-out, background-color 0.1s',
                overflow: 'hidden'
              }}
            >
              {/* Header */}
              <div 
                onDoubleClick={() => toggleChat(agent.id)}
                style={{
                  padding: '6px 10px',
                  display: 'flex',
                  alignItems: 'flex-start',
                  cursor: 'pointer',
                  userSelect: 'none',
                  backgroundColor: isOpen ? 'var(--bg3)' : 'transparent',
                  borderBottom: isOpen ? '1px solid var(--border0)' : 'none'
                }}
                title="Double click to expand"
              >
                <div style={{ paddingTop: '2px' }}><StatusLight status={agent.status} /></div>
                <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', marginBottom: isOpen ? 0 : '2px' }}>
                    <span className="mono" style={{ 
                      fontSize: '11px', 
                      fontWeight: 600, 
                      color: isOpen ? 'var(--text0)' : 'var(--text1)', 
                      marginRight: '8px' 
                    }}>{agent.name}</span>
                    <span style={{ fontSize: '9px', color: 'var(--text2)', textTransform: 'uppercase' }}>{agent.role}</span>
                  </div>
                  
                  {/* Collapsed Message Preview */}
                  {!isOpen && (
                    <div style={{ 
                      fontSize: '10px', 
                      color: 'var(--text2)', 
                      whiteSpace: 'nowrap', 
                      overflow: 'hidden', 
                      textOverflow: 'ellipsis',
                      fontFamily: 'system-ui'
                    }}>
                      {agent.lastMessage}
                    </div>
                  )}
                </div>
              </div>

              {/* Expanded Content */}
              {isOpen && (
                <>
                  <div 
                    className="mono"
                    ref={(el) => { scrollRefs.current[agent.id] = el; }}
                    style={{
                      flex: 1,
                      padding: '12px',
                      fontSize: '11px',
                      color: 'var(--text1)',
                      overflowY: 'auto',
                      backgroundColor: 'var(--bg0)',
                    }}
                  >
                    {agent.history.map((line, idx) => {
                      const isSystem = line.startsWith('[SYSTEM]');
                      const isUser = line.startsWith('[USER]');
                      const isThought = line.startsWith('[THOUGHT]');
                      const isAction = line.startsWith('[ACTION]');
                      
                      return (
                        <div key={idx} style={{ 
                          marginBottom: '8px', 
                          lineHeight: '1.5',
                          wordBreak: 'break-word',
                          color: isSystem ? 'var(--text2)' : isUser ? 'var(--text0)' : isThought ? 'var(--purple)' : isAction ? 'var(--warning)' : 'inherit'
                        }}>
                          {line}
                        </div>
                      );
                    })}
                  </div>
                  
                  {/* Chat Input */}
                  <div style={{
                    padding: '8px',
                    backgroundColor: 'var(--bg1)',
                    borderTop: '1px solid var(--border1)'
                  }}>
                    <div style={{ display: 'flex', gap: '8px' }}>
                       <textarea 
                          value={inputVal}
                          onChange={(e) => setInputVal(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                              e.preventDefault();
                              handleSend();
                            }
                          }}
                          placeholder="Command agent..."
                          style={{
                            flex: 1,
                            background: 'var(--bg0)',
                            border: '1px solid var(--border1)',
                            borderRadius: '2px',
                            color: 'var(--text0)',
                            padding: '6px',
                            fontSize: '11px',
                            outline: 'none',
                            fontFamily: 'inherit',
                            resize: 'none',
                            minHeight: '32px'
                          }}
                       />
                       <button 
                         onClick={handleSend}
                         style={{
                           background: 'var(--accent-dim)',
                           border: '1px solid var(--accent)',
                           color: 'var(--accent)',
                           borderRadius: '2px',
                           cursor: 'pointer',
                           padding: '0 12px',
                           fontWeight: 600
                         }}
                       >
                         ↵
                       </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const App = () => {
  const [columns, setColumns] = useState<KanbanColumn[]>(INITIAL_KANBAN);
  const { agents, sendMessage } = useAgentRuntime(INITIAL_AGENTS);
  const [openChatId, setOpenChatId] = useState<number>(10);

  const addCard = (columnId: string, title: string) => {
    const newCard: KanbanCard = {
      id: `T-${Math.floor(Math.random() * 1000)}`,
      title,
      tag: 'NEW',
      assignee: 'Unassigned'
    };

    setColumns(prev => prev.map(col => {
      if (col.id === columnId) {
        return { ...col, cards: [newCard, ...col.cards] };
      }
      return col;
    }));
  };

  const deleteCard = (columnId: string, cardId: string) => {
    setColumns(prev => prev.map(col => {
      if (col.id === columnId) {
        return { ...col, cards: col.cards.filter(c => c.id !== cardId) };
      }
      return col;
    }));
  };

  const updateCard = (columnId: string, cardId: string, newTitle: string) => {
    setColumns(prev => prev.map(col => {
      if (col.id === columnId) {
        return { 
          ...col, 
          cards: col.cards.map(c => c.id === cardId ? { ...c, title: newTitle } : c) 
        };
      }
      return col;
    }));
  };

  const moveCard = (cardId: string, sourceColId: string, targetColId: string, targetIndex?: number) => {
    setColumns(prev => {
      const newCols = [...prev];
      const sourceCol = newCols.find(c => c.id === sourceColId);
      const targetCol = newCols.find(c => c.id === targetColId);

      if (!sourceCol || !targetCol) return prev;

      const cardIndex = sourceCol.cards.findIndex(c => c.id === cardId);
      if (cardIndex === -1) return prev;

      const [cardToMove] = sourceCol.cards.splice(cardIndex, 1);

      if (targetIndex !== undefined) {
        // Drop on specific position
        targetCol.cards.splice(targetIndex, 0, cardToMove);
      } else {
        // Drop at end
        targetCol.cards.push(cardToMove);
      }

      return newCols;
    });
  };

  // Triggered when clicking the Robot icon on a card
  const handleAnalyzeTask = (card: KanbanCard) => {
    // 1. Pick an agent (simple round-robin or first available, here we pick Agent 10 for demo)
    const targetAgentId = 10;
    
    // 2. Open that chat
    setOpenChatId(targetAgentId);

    // 3. Send context prompt
    const prompt = `Please analyze task ${card.id}: "${card.title}". Identify dependencies and suggest next steps.`;
    sendMessage(targetAgentId, prompt);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', backgroundColor: 'var(--bg0)' }}>
      <Header />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{
          flex: 3,
          display: 'flex',
          backgroundColor: 'var(--bg0)',
          borderRight: '1px solid var(--border0)',
          padding: '0',
          gap: '1px', 
          overflowX: 'auto'
        }}>
          {columns.map(col => (
            <KanbanColumnComponent 
              key={col.id} 
              column={col} 
              onAddCard={addCard}
              onDeleteCard={deleteCard}
              onUpdateCard={updateCard}
              onMoveCard={moveCard}
              onAnalyzeCard={handleAnalyzeTask}
            />
          ))}
        </div>
        <ChatPane 
          agents={agents} 
          openChatId={openChatId} 
          setOpenChatId={setOpenChatId}
          onSendMessage={sendMessage}
        />
      </div>
    </div>
  );
};

const root = createRoot(document.getElementById('root')!);
root.render(<App />);